"""Identity, personal NOVA (preferences, onboarding) and ORBIT account linking."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from nova.domain.agents import AgentProfile
from nova.domain.context import ContextError
from nova.domain.enums import AutonomyMode
from nova.infra.db import get_session, utcnow
from nova.infra.models import User, UserPreferences
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
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "title": user.title,
        "is_admin": user.is_admin,
        "roles": user.realm_roles,
        "preferences": preferences_dict(prefs, user),
        "orbit": identity.model_dump(mode="json"),
    }


@router.get("/me")
async def me(principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    return await _me(session, principal.user_id)


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
            raise ApiError(401, "orbit_login_failed", "ORBIT rejected these credentials.") from exc
        raise
    await audit(
        session,
        actor_id=principal.user_id,
        action="orbit.link",
        target_type="user",
        target_id=principal.user_id,
        summary=f"Linked ORBIT account {identity.email}",
    )
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
