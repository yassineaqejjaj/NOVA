"""Users, preferences and principals."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.config import get_settings
from nova.domain.permissions import Principal
from nova.infra.db import utcnow
from nova.infra.models import OrbitAccount, User, UserPreferences
from nova.services import workspaces

SERVICE_SUBJECT = "service:forge-evaluation"


def principal_for(user: User, clearance: int | None = None) -> Principal:
    """The principal of ``user``. Without an explicit ``clearance`` it is the default policy (C1): fail-closed.

    Call sites with a session use ``resolve_principal``, which reads the clearance ORBIT gave the user.
    """
    level = get_settings().default_clearance if clearance is None else max(0, min(3, int(clearance)))
    return Principal(
        user_id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        realm_roles=frozenset(user.realm_roles or []),
        is_admin=user.is_admin,
        is_service=user.is_service,
        clearance=level,
        workspace_id=str(workspaces.workspace_of_request(user.__dict__.get("workspace_id"))),
    )


async def resolve_principal(session: AsyncSession, user: User) -> Principal:
    """The principal with the clearance of the user's linked ORBIT account, or the default policy without one.

    Read on every request (not cached in the session cookie): a clearance lowered in ORBIT applies at the next call.
    """
    clearance = await session.scalar(select(OrbitAccount.clearance).where(OrbitAccount.user_id == user.id))
    return principal_for(user, clearance)


async def upsert_user(
    session: AsyncSession,
    *,
    subject: str,
    email: str,
    display_name: str,
    realm_roles: list[str],
    is_admin: bool,
    is_service: bool = False,
    email_verified: bool = False,
    workspace_id: uuid.UUID | None = None,
) -> User:
    """Find or create the account of ``subject``. ``workspace_id`` (a validated token's ``orion_workspace_id``) is the
    workspace of an account *created* here; an existing account keeps its own (a workspace never changes)."""
    user = await session.scalar(select(User).where(User.subject == subject))
    if user is None and email:
        # A seeded account (or, with an SSO-verified email, a local dev account) is adopted by its owner's first
        # real sign-in. Dev accounts cannot exist in production (dev sign-in is refused there).
        prefixes = ("seed:", "dev:") if email_verified else ("seed:",)
        seeded = await session.scalar(
            select(User).where(User.email == email.lower(), or_(*(User.subject.startswith(p) for p in prefixes)))
        )
        if seeded is not None:
            seeded.subject = subject
            user = seeded
    if user is None:
        user = User(
            subject=subject,
            email=email,
            display_name=display_name or email.split("@")[0],
            realm_roles=realm_roles,
            is_admin=is_admin,
            is_service=is_service,
        )
        if workspace_id is not None and workspaces.enabled():
            await workspaces.ensure_workspace(session, workspace_id)
            user.workspace_id = workspace_id
        session.add(user)
        await session.flush()
        session.add(UserPreferences(user_id=user.id))
        await session.flush()
        await session.refresh(user)
    else:
        user.email, user.realm_roles, user.is_admin = email, realm_roles, is_admin
        if display_name:
            user.display_name = display_name
    user.last_seen_at = utcnow()
    return user


async def service_user(session: AsyncSession) -> User:
    """Principal used for FORGE-initiated evaluation runs (no ORBIT access, no external writes)."""
    return await upsert_user(
        session,
        subject=SERVICE_SUBJECT,
        email="forge-evaluation@nova.local",
        display_name="FORGE evaluation",
        realm_roles=[],
        is_admin=False,
        is_service=True,
    )


def preferences_dict(prefs: UserPreferences | None, user: User) -> dict[str, Any]:
    if prefs is None:
        return {"nova_name": "NOVA", "role": user.title, "language": None, "orb_color": "coral", "profile": "product"}
    return {
        "nova_name": prefs.nova_name,
        "avatar": prefs.avatar,
        "tone": prefs.tone,
        "role": prefs.role or user.title,
        "teams": prefs.teams,
        "preferred_methods": prefs.preferred_methods,
        "artifact_format": prefs.artifact_format,
        "default_autonomy": prefs.default_autonomy,
        "theme": prefs.theme,
        "language": prefs.language,
        "orb_color": prefs.orb_color or "coral",
        "profile": prefs.profile or "product",
        "action_permissions": prefs.action_permissions or {},
        "onboarding_completed": prefs.onboarding_completed_at is not None,
    }


async def get_user(session: AsyncSession, user_id: str | uuid.UUID) -> User | None:
    return await session.get(User, user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id)))
