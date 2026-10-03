"""Users, preferences and principals."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.domain.permissions import Principal
from nova.infra.db import utcnow
from nova.infra.models import User, UserPreferences

SERVICE_SUBJECT = "service:forge-evaluation"


def principal_for(user: User) -> Principal:
    return Principal(
        user_id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        realm_roles=frozenset(user.realm_roles or []),
        is_admin=user.is_admin,
        is_service=user.is_service,
    )


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
) -> User:
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
        return {"nova_name": "NOVA", "role": user.title}
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
        "onboarding_completed": prefs.onboarding_completed_at is not None,
    }


async def get_user(session: AsyncSession, user_id: str | uuid.UUID) -> User | None:
    return await session.get(User, user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id)))
