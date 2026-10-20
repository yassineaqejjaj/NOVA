"""What the links screen shows when delegation is federated (ADR 001 §11, NOV-114).

Only active with ``NOVA_DELEGATION_MODE=token_exchange``; in ``linked_session`` (the default) ``GET /me/links`` is exactly what it
was. Everything here is read from what NOVA already recorded (``delegation_sessions``, the ORBIT account's revocation, the
projects' references): **no call to the IdP or to a service when the screen opens**, no token, no secret, no response body.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.config import Settings
from nova.domain.permissions import Principal
from nova.infra.db import aware, utcnow
from nova.infra.models import DelegationSession, OrbitAccount, ProjectReference, User
from nova.services import workspaces

SERVICES = ("orbit", "forge")
#: States of a federated link (ADR 001 §11). ``fallback`` (agent key) cannot happen here: the delegation never falls back.
STATES = ("ok", "expiring", "expired", "revoked", "degraded", "unlinked", "not_configured")
SUBJECT_ERRORS = ("subject_expired", "subject_missing", "user_disabled")
ACTIONS = {"orbit": ["reconnect", "revoke", "test"], "forge": ["reconnect", "revoke"]}


def abbreviate(sub: str | None) -> str | None:
    """``5b1d0000…``: enough to tell two accounts apart in a ticket, not enough to be one."""
    return None if not sub else (sub if len(sub) <= 8 else f"{sub[:8]}…")


def mask_email(email: str | None) -> str | None:
    local, _, domain = (email or "").partition("@")
    return None if not email else (f"{local[:1]}***@{domain}" if domain else "***")


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _seconds_left(expires_at: datetime | None, now: datetime) -> int | None:
    return None if expires_at is None else max(0, int((expires_at - now).total_seconds()))


def state_of(
    service: str,
    *,
    row: DelegationSession | None,
    entry: dict[str, Any],
    orbit_revoked: bool,
    settings: Settings,
    now: datetime,
) -> str:
    if row is None or not (row.access_ciphertext or row.refresh_ciphertext):
        return "not_configured" if service == "forge" and not settings.forge_api_key and not entry else "unlinked"
    if not entry and service == "forge" and not settings.forge_api_key:
        return "not_configured"
    if entry.get("revoked_by_user") or (service == "orbit" and orbit_revoked):
        return "revoked"
    session_gone = (
        entry.get("last_error") in SUBJECT_ERRORS
        or (row.refresh_ciphertext is None and row.access_expires_at is not None and aware(row.access_expires_at) <= now)
        or (row.refresh_expires_at is not None and aware(row.refresh_expires_at) <= now)
    )
    if session_gone:
        return "expired"
    if not entry:  # a sign-in exists but this service was never reached: nothing is proven yet
        return "unlinked"
    if entry.get("status") == "error" or int(entry.get("call_errors", 0)) > 0:
        return "degraded"
    expires = _when(entry.get("expires_at"))
    remaining = _seconds_left(expires, now)
    if remaining is not None and 0 < remaining <= settings.links_expiry_warning_seconds:
        return "expiring"
    return "ok"


def _clearance(local: int, cap: int | None) -> dict[str, Any]:
    effective = workspaces.capped_clearance(local, cap)
    reason = "no_cap" if cap is None else "capped_by_token" if cap < local else "local"
    return {"local": local, "cap": cap, "effective": effective, "reason": reason}


async def _alias(session: AsyncSession, project_key: str | None) -> tuple[str | None, str | None]:
    """(orion_project_id, local alias) of the project a delegated token was for: from the references NOVA already holds."""
    if not project_key or project_key == "-":
        return None, None
    if project_key.startswith("slug:"):
        return None, project_key.removeprefix("slug:")
    try:
        orion = uuid.UUID(project_key)
    except ValueError:
        return None, None
    alias = await session.scalar(
        select(ProjectReference.external_id).where(ProjectReference.system == "orbit", ProjectReference.orion_project_id == orion)
    )
    return str(orion), alias


async def service_entry(
    session: AsyncSession,
    service: str,
    *,
    user: User,
    local_clearance: int,
    row: DelegationSession | None,
    settings: Settings,
    now: datetime,
) -> dict[str, Any]:
    entry = dict((row.links or {}).get(service) or {}) if row else {}
    account = await session.get(OrbitAccount, user.id) if service == "orbit" else None
    orbit_revoked = bool(account and account.revoked_at is not None)
    status = state_of(service, row=row, entry=entry, orbit_revoked=orbit_revoked, settings=settings, now=now)
    project_id, alias = await _alias(session, entry.get("project_key"))
    expires = _when(entry.get("expires_at"))
    revoked_reason = None
    if status == "revoked":
        revoked_reason = "user" if entry.get("revoked_by_user") else (account.revoked_reason or "orbit") if account else "orbit"
    return {
        "service": service,
        "status": status,
        "linked": status not in ("unlinked", "not_configured"),
        "revoked_reason": revoked_reason,
        "identity": {
            "sub": abbreviate(entry.get("subject")),
            "email": user.email,
            "issuer": entry.get("issuer"),
            "amr": entry.get("amr") or [],
            "act": abbreviate(entry.get("actor")),
        },
        "project": {
            "orion_project_id": project_id or entry.get("project_id"),
            "alias": alias,
            "workspace_id": entry.get("workspace_id"),
        },
        "expiry": {
            "expires_at": entry.get("expires_at"),
            "remaining_seconds": _seconds_left(expires, now),
            "session_expires_at": aware(row.refresh_expires_at).isoformat() if row and row.refresh_expires_at else None,
            "renewal": "on_demand",  # a delegated token is exchanged again at the next call, never stored
        },
        "scope": {
            "scopes": entry.get("scopes") or [],
            "roles": entry.get("roles") or [],
            "clearance": _clearance(local_clearance, entry.get("clearance_cap")),
        },
        "last_exchange": {
            "at": entry.get("last_success_at"),
            "status": "ok" if entry.get("status") == "ok" else entry.get("last_error"),
            "exchange_ms": entry.get("exchange_ms"),
            "consecutive_errors": int(entry.get("consecutive_errors", 0)),
            "last_error": entry.get("last_error"),
            "last_error_at": entry.get("last_error_at"),
        },
        "roundtrip": entry.get("roundtrip"),  # {at, operation, status, latency_ms}
        "call_errors": int(entry.get("call_errors", 0)),
        "actions": ACTIONS[service] if status not in ("not_configured",) else [],
    }


async def user_links(session: AsyncSession, principal: Principal, settings: Settings) -> dict[str, Any]:
    """The federated links of the signed-in user (their own, read only)."""
    user = await session.get(User, uuid.UUID(principal.user_id))
    assert user is not None
    row = await session.get(DelegationSession, user.id)
    now = utcnow()
    now = now if now.tzinfo else now.replace(tzinfo=UTC)
    return {
        "mode": "token_exchange",
        "expiry_warning_seconds": settings.links_expiry_warning_seconds,
        "services": {
            s: await service_entry(
                session, s, user=user, local_clearance=principal.clearance, row=row, settings=settings, now=now
            )
            for s in SERVICES
        },
    }


async def workspace_links(
    session: AsyncSession, principal: Principal, settings: Settings, *, limit: int = 500
) -> list[dict[str, Any]]:
    """For an administrator: the state of the links of the workspace's members. Statuses only: no identity detail, no content."""
    query = (
        select(DelegationSession, User).join(User, User.id == DelegationSession.user_id).order_by(User.display_name).limit(limit)
    )
    if workspaces.enabled():
        query = query.where(DelegationSession.workspace_id == uuid.UUID(principal.workspace_id))
    now = utcnow()
    now = now if now.tzinfo else now.replace(tzinfo=UTC)
    members = []
    for row, user in (await session.execute(query)).all():
        services = {}
        for s in SERVICES:
            entry = dict((row.links or {}).get(s) or {})
            account = await session.get(OrbitAccount, user.id) if s == "orbit" else None
            status = state_of(
                s,
                row=row,
                entry=entry,
                orbit_revoked=bool(account and account.revoked_at is not None),
                settings=settings,
                now=now,
            )
            services[s] = {
                "status": status,
                "last_error": entry.get("last_error"),
                "consecutive_errors": int(entry.get("consecutive_errors", 0)),
                "expires_at": entry.get("expires_at"),
                "roundtrip": entry.get("roundtrip"),
            }
        members.append(
            {"user_id": str(user.id), "name": user.display_name, "email": mask_email(user.email), "services": services}
        )
    return members
