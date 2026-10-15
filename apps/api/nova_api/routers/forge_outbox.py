"""State of the FORGE capture outbox (services/forge_outbox.py): for administrators and for Prometheus."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from nova.infra.db import get_session
from nova.services import forge_outbox
from nova_api.auth import CurrentPrincipal
from nova_api.errors import ApiError

router = APIRouter(prefix="/admin/forge-outbox", tags=["forge-outbox"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _admin(principal: Any) -> None:
    if not principal.is_admin:
        raise ApiError(403, "forbidden", "Only an administrator can see the FORGE capture queue.")


@router.get("")
async def outbox_state(principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    """Rows per status (pending / sent / failed / skipped) and the age of the oldest capture still waiting."""
    _admin(principal)
    return await forge_outbox.stats(session)


@router.get("/metrics", response_class=PlainTextResponse)
async def outbox_metrics(principal: CurrentPrincipal, session: SessionDep) -> str:
    """The same numbers in Prometheus text format (scrape with an administrator's credentials)."""
    _admin(principal)
    return forge_outbox.prometheus(await forge_outbox.stats(session))
