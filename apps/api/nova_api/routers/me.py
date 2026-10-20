"""Identity, personal NOVA (preferences, onboarding) and ORBIT account linking."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from nova.config import get_settings
from nova.domain.agents import AgentProfile
from nova.domain.context import ContextError, ContextIdentity
from nova.domain.enums import AutonomyMode
from nova.domain.permissions import ACTION_DEFAULTS, ACTIONS
from nova.infra.db import get_session, utcnow
from nova.infra.models import OrbitAccount, User, UserPreferences
from nova.integrations import link_health
from nova.integrations.forge import connection as forge_connection
from nova.services import providers
from nova.services.audit import audit
from nova.services.projects import sync_from_orbit
from nova.services.users import preferences_dict
from nova_api.auth import CurrentPrincipal, LooseEmail
from nova_api.errors import ApiError

router = APIRouter(tags=["me"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


OrbColor = Literal["coral", "rose", "violet", "ocean", "emerald", "amber", "graphite"]


class PreferencesIn(BaseModel):
    nova_name: str | None = Field(default=None, min_length=1, max_length=60)
    avatar: str | None = Field(default=None, max_length=40)
    tone: str | None = Field(default=None, max_length=120)
    role: str | None = Field(default=None, max_length=120)
    teams: list[str] | None = Field(default=None, max_length=20)
    preferred_methods: list[str] | None = Field(default=None, max_length=20)
    artifact_format: Literal["structured", "concise", "detailed"] | None = None
    default_autonomy: AutonomyMode | None = None
    theme: Literal["dark", "light", "system"] | None = None
    language: Literal["en", "fr"] | None = None
    orb_color: OrbColor | None = None
    profile: AgentProfile | None = None
    # Always / Ask / Never per action; the full map replaces the previous one (a missing action follows the level)
    action_permissions: dict[str, Literal["always", "ask", "never"]] | None = None

    @field_validator("action_permissions")
    @classmethod
    def _known_actions(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        unknown = set(value or {}) - set(ACTIONS)
        if unknown:
            raise ValueError(f"Unknown actions: {', '.join(sorted(unknown))}")
        return value


class OnboardingIn(PreferencesIn):
    title: str | None = Field(default=None, max_length=200)


class OrbitLinkIn(BaseModel):
    email: LooseEmail
    password: str = Field(min_length=1, max_length=500)


async def _me(session: AsyncSession, user_id: str) -> dict[str, Any]:
    user = await session.get(User, uuid.UUID(user_id))
    assert user is not None
    prefs = await session.get(UserPreferences, user.id)
    identity = await providers.context().identity(user_id)
    settings = get_settings()
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "title": user.title,
        "is_admin": user.is_admin,
        "roles": user.realm_roles,
        "preferences": preferences_dict(prefs, user),
        "orbit": identity.model_dump(mode="json"),
        # Nova Context (ORBIT) and Nova Quality (FORGE): where the menu entries open
        "apps": {"context_url": settings.orbit_public_url, "quality_url": settings.forge_public_url},
    }


@router.get("/me")
async def me(principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    return await _me(session, principal.user_id)


def _later(a: Any, b: Any) -> bool:
    """``a`` is a more recent timestamp than ``b`` (``b`` may be missing)."""
    return a is not None and (b is None or a > b)


def _orbit_status(identity: ContextIdentity) -> str:
    if identity.fallback:
        return "fallback"  # the session is gone: the project agent key acts, with its own (reduced) clearance
    if identity.session_expired:
        return "expired"
    if not identity.linked:
        return "agent_key" if identity.mode == "agent_key" else "unlinked"
    return "degraded" if _later(identity.last_error_at, identity.last_success_at) else "ok"


def _public_endpoint(url: str) -> str:
    """Scheme, host and port of a configured URL: never a user, a password, a path or a query."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname}{f':{parts.port}' if parts.port else ''}" if parts.hostname else ""


async def _forge_link(settings: Any) -> dict[str, Any]:
    state = await link_health.forge_state()
    if not settings.forge_api_key:
        status = "not_configured"
    else:
        status = "degraded" if _later(state["last_error_at"], state["last_success_at"]) else "ok"
    return {
        "status": status,
        "configured": bool(settings.forge_api_key),
        "endpoint": _public_endpoint(settings.forge_base_url),
        "api_key_present": bool(settings.forge_api_key),
        "inbound_credential_set": bool(settings.forge_credential_id),
        # How FORGE calls NOVA back, and what is wrong with it (names of settings, never their values)
        "callback_endpoint": _public_endpoint(forge_connection.forge_callback_endpoint(settings)),
        "problems": forge_connection.connection_problems(settings),
        "capture_policy": settings.forge_capture_policy,
        "capture_mode": settings.forge_capture_mode,
        **state,
        "capture_queue": None,  # no capture outbox yet: not available
    }


@router.get("/me/links")
async def links(principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    """Health of the ORBIT and FORGE links: who acts, until when, with which clearance, last exchange. Never a secret."""
    provider = providers.context()
    identity = await provider.identity(principal.user_id)
    keys_status = getattr(provider, "agent_keys_status", None)
    agent_keys = await keys_status() if keys_status and identity.agent_projects else []
    orbit = {**identity.model_dump(mode="json"), "status": _orbit_status(identity), "agent_keys": agent_keys}
    revoked = await session.get(OrbitAccount, uuid.UUID(principal.user_id))
    if revoked is not None and revoked.revoked_at is not None:  # ORBIT removed this member (NOV-81): link again
        orbit.update(status="revoked", revoked_at=revoked.revoked_at.isoformat(), revoked_reason=revoked.revoked_reason)
    return {"orbit": orbit, "forge": await _forge_link(get_settings()) if principal.is_admin else None}


async def _apply(prefs: UserPreferences, body: PreferencesIn) -> None:
    for field, value in body.model_dump(exclude_unset=True, exclude={"title"}).items():
        if value is not None:
            setattr(prefs, field, value.value if isinstance(value, AutonomyMode) else value)


@router.patch("/me/preferences")
async def update_preferences(body: PreferencesIn, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    prefs = await session.get(UserPreferences, uuid.UUID(principal.user_id))
    assert prefs is not None
    await _apply(prefs, body)
    await session.commit()
    return await _me(session, principal.user_id)


@router.get("/me/permissions")
async def permissions(principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    """The Always / Ask / Never matrix: defaults per autonomy level and the user's own choices."""
    prefs = await session.get(UserPreferences, uuid.UUID(principal.user_id))
    return {
        "actions": [{"id": a, "defaults": {m.value: v for m, v in ACTION_DEFAULTS[a].items()}} for a in ACTIONS],
        "values": (prefs.action_permissions if prefs else None) or {},
        "default_autonomy": prefs.default_autonomy if prefs else "assist",
        "external_writes_need_approval": not get_settings().policy_allow_auto_external_writes,
        # Connectors NOVA will act on once available (shown, not usable yet)
        "connectors": [{"id": c, "available": False} for c in ("jira", "slack", "analytics")],
    }


@router.post("/me/onboarding")
async def complete_onboarding(body: OnboardingIn, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    user = await session.get(User, uuid.UUID(principal.user_id))
    prefs = await session.get(UserPreferences, uuid.UUID(principal.user_id))
    assert user is not None and prefs is not None
    if body.title:
        user.title = body.title
    await _apply(prefs, body)
    prefs.onboarding_completed_at = utcnow()
    await audit(session, actor_id=user.id, action="onboarding.complete", target_type="user", target_id=str(user.id))
    await session.commit()
    return await _me(session, principal.user_id)


@router.post("/me/orbit")
async def link_orbit(body: OrbitLinkIn, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    """Link the user's ORBIT account. The password is used once to obtain an ORBIT session and never stored."""
    provider = providers.context()
    link = getattr(provider, "link_account", None)
    if link is None:
        raise ApiError(400, "not_supported", "This context provider does not support account linking.")
    try:
        identity = await link(principal.user_id, str(body.email), body.password)
    except ContextError as exc:
        if exc.code == "unauthorized":
            raise ApiError(409, "orbit_login_failed", "ORBIT rejected these credentials.") from exc
        raise
    await audit(
        session,
        actor_id=principal.user_id,
        action="orbit.link",
        target_type="user",
        target_id=principal.user_id,
        summary=f"Linked ORBIT account {identity.email}",
    )
    await session.commit()  # the sync below talks to ORBIT, which records the health of the link in its own transaction
    synced = await sync_from_orbit(session, principal)
    await session.commit()
    return {"orbit": identity.model_dump(mode="json"), "projects_synced": synced}


@router.delete("/me/orbit", status_code=204)
async def unlink_orbit(principal: CurrentPrincipal, session: SessionDep) -> None:
    unlink = getattr(providers.context(), "unlink_account", None)
    if unlink:
        await unlink(principal.user_id)
    await audit(session, actor_id=principal.user_id, action="orbit.unlink", target_type="user", target_id=principal.user_id)
    await session.commit()
