"""Figma account linking: OAuth 2.1 + PKCE for the Figma MCP server, or a personal access token (read only)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from nova.config import get_settings
from nova.domain.design import DesignError
from nova.infra.db import get_session
from nova.integrations.figma.adapter import FigmaDesignProvider
from nova.integrations.figma.oauth import read_state
from nova.services import providers
from nova.services.audit import audit
from nova_api.auth import CurrentPrincipal
from nova_api.errors import ApiError

router = APIRouter(tags=["figma"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


class FigmaTokenIn(BaseModel):
    token: str = Field(min_length=8, max_length=500)


def _provider() -> FigmaDesignProvider:
    provider = providers.design()
    if not isinstance(provider, FigmaDesignProvider):
        raise ApiError(400, "not_supported", "This design provider does not support account linking.")
    return provider


def _api_error(exc: DesignError) -> ApiError:
    status = {"not_connected": 409, "forbidden": 403, "not_found": 404, "unavailable": 503, "invalid": 400}.get(exc.code, 400)
    return ApiError(status, f"figma_{exc.code}", exc.message)


@router.get("/me/figma")
async def figma_status(principal: CurrentPrincipal) -> dict[str, Any]:
    return (await providers.design().status(principal.user_id)).model_dump(mode="json")


@router.post("/me/figma/connect")
async def figma_connect(principal: CurrentPrincipal) -> dict[str, str]:
    provider = _provider()
    if not provider.oauth.available:
        raise ApiError(409, "figma_oauth_unavailable", "Figma OAuth is not configured: use a personal access token instead.")
    try:
        return {"authorize_url": await provider.oauth.authorize_url(principal.user_id)}
    except DesignError as exc:
        raise _api_error(exc) from exc


@router.get("/me/figma/callback")
async def figma_callback(
    principal: CurrentPrincipal,
    session: SessionDep,
    state: str = Query(default=""),
    code: str = Query(default=""),
    error: str = Query(default=""),
) -> RedirectResponse:
    """Browser redirect from Figma: the encrypted ``state`` carries the PKCE verifier and must match the session user."""
    web = get_settings().public_url.rstrip("/")
    if error or not code:
        return RedirectResponse(f"{web}/settings?figma=denied", status_code=302)
    provider = _provider()
    try:
        user_id, verifier = read_state(state)
        if user_id != principal.user_id:
            raise DesignError("invalid", "This Figma authorization belongs to another session")
        tokens = await provider.oauth.exchange_code(code, verifier)
    except DesignError as exc:
        raise _api_error(exc) from exc
    await provider.save_oauth(principal.user_id, tokens, handle=await _handle(provider, tokens.access_token))
    await audit(
        session,
        actor_id=principal.user_id,
        action="figma.link",
        target_type="user",
        target_id=principal.user_id,
        summary="Linked Figma (MCP, OAuth)",
    )
    await session.commit()
    return RedirectResponse(f"{web}/settings?figma=connected", status_code=302)


async def _handle(provider: FigmaDesignProvider, access_token: str) -> str:
    """Best effort: the OAuth token may not be accepted by the REST API, the handle is cosmetic."""
    try:
        me = await provider.validate_token(access_token)
    except DesignError:
        return ""
    return str(me.get("handle") or me.get("email") or "")


@router.post("/me/figma/token")
async def figma_link_token(body: FigmaTokenIn, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    provider = _provider()
    try:
        me = await provider.validate_token(body.token.strip())
    except DesignError as exc:
        if exc.code in ("not_connected", "forbidden"):
            raise ApiError(409, "figma_token_invalid", "Figma rejected this token.") from exc
        raise _api_error(exc) from exc
    handle = str(me.get("handle") or me.get("email") or "")
    await provider.save_token(principal.user_id, body.token.strip(), figma_user_id=str(me.get("id") or ""), handle=handle)
    await audit(
        session,
        actor_id=principal.user_id,
        action="figma.link",
        target_type="user",
        target_id=principal.user_id,
        summary=f"Linked Figma account {handle} (personal token, read only)",
    )
    await session.commit()
    return (await provider.status(principal.user_id)).model_dump(mode="json")


@router.delete("/me/figma", status_code=204)
async def figma_unlink(principal: CurrentPrincipal, session: SessionDep) -> None:
    await _provider().unlink(principal.user_id)
    await audit(session, actor_id=principal.user_id, action="figma.unlink", target_type="user", target_id=principal.user_id)
    await session.commit()
