"""ORBIT revocation events: the signed webhook ORBIT calls, and the administrator's view and replay (NOV-81).

``POST /api/v1/webhooks/orbit`` has no session: it is authenticated by ``X-Orbit-Signature``
(``sha256=<HMAC-SHA256(secret, raw body)>``, secret ``NOVA_ORBIT_WEBHOOK_SECRET``). Without a secret it answers 503.
The payload follows ORBIT's revocation events (NOV-80); see docs/OPERATIONS.md.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.config import get_settings
from nova.infra.db import aware, get_session
from nova.infra.models import OrbitEvent
from nova.services import revocation
from nova_api.auth import CurrentPrincipal
from nova_api.errors import ApiError

router = APIRouter(tags=["orbit-events"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
LISTED = 50


@router.post("/webhooks/orbit")
async def receive(
    request: Request,
    session: SessionDep,
    x_orbit_signature: str = Header(default=""),
    x_orbit_delivery: str = Header(default=""),
    x_orbit_event: str = Header(default=""),
) -> dict[str, Any]:
    secret = get_settings().orbit_webhook_secret
    if not secret:
        raise ApiError(503, "webhook_not_configured", "The ORBIT webhook is not configured.")
    body = await request.body()
    if len(body) > revocation.MAX_BODY:
        raise ApiError(413, "too_large", "The event is too large.")
    if not revocation.verify(secret, body, x_orbit_signature):  # constant time, before anything is read
        raise ApiError(401, "invalid_signature", "Invalid signature.")
    try:
        raw = json.loads(body)
    except ValueError as exc:
        raise ApiError(400, "invalid_event", "The body is not JSON.") from exc
    if x_orbit_event == "ping":
        return {"status": "pong"}
    try:
        event = revocation.parse(raw if isinstance(raw, dict) else {})
        status, effects = await revocation.receive(session, event, x_orbit_delivery or event.id)
    except revocation.RevocationError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from exc
    await session.commit()
    return {"status": status, "effects": effects}


def _admin(principal: Any) -> None:
    if not principal.is_admin:
        raise ApiError(403, "forbidden", "Only an administrator can see or replay ORBIT events.")


def _view(row: OrbitEvent) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "delivery_id": row.delivery_id,
        "type": row.type,
        "project": row.project_slug,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "status": row.status,
        "effects": row.effects,
        "error": row.error,
        "received_at": aware(row.received_at).isoformat(),
        "processed_at": aware(row.processed_at).isoformat() if row.processed_at else None,
    }


@router.get("/admin/orbit-events")
async def events(principal: CurrentPrincipal, session: SessionDep) -> list[dict[str, Any]]:
    _admin(principal)
    rows = await session.scalars(select(OrbitEvent).order_by(OrbitEvent.received_at.desc()).limit(LISTED))
    return [_view(r) for r in rows]


@router.post("/admin/orbit-events/{event_id}/replay")
async def replay(event_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    """Apply the effects of a stored event again (they are idempotent): after a failure, or a restored backup."""
    _admin(principal)
    try:
        row = await session.get(OrbitEvent, uuid.UUID(event_id))
    except ValueError:
        row = None
    if row is None:
        raise ApiError(404, "not_found", "Event not found.")
    effects = await revocation.apply(session, row, replayed=True)
    await session.commit()
    return {"status": row.status, "effects": effects}
