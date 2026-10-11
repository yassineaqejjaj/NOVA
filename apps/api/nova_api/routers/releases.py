"""Releases of learned policies (canary, approval, rollback): status for everyone, decisions for admins."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.config import get_settings
from nova.infra.db import get_session
from nova.infra.models import Release
from nova.services import releases
from nova_api.auth import CurrentPrincipal
from nova_api.errors import ApiError

router = APIRouter(prefix="/releases", tags=["releases"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
HISTORY = 30


def _admin(principal: Any) -> None:
    if not principal.is_admin:
        raise ApiError(403, "forbidden", "Only an administrator can decide on a release.")


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ApiError(404, "not_found", "Not found.") from exc


def _error(exc: releases.ReleaseError) -> ApiError:
    return ApiError({"not_found": 404, "conflict": 409}.get(exc.code, 422), exc.code, exc.message)


async def _view(session: AsyncSession, release: Release) -> dict[str, Any]:
    canary, control = await releases.stats(session, release)
    settings = get_settings()
    return {
        "id": str(release.id),
        "agent": release.agent,
        "label": release.label,
        "status": release.status,
        "canary_percent": release.canary_percent,
        "policy_id": str(release.policy_id),
        "baseline_policy_id": str(release.baseline_policy_id) if release.baseline_policy_id else None,
        "evidence": release.evidence,
        "reason": release.reason,
        "decided_by": release.decided_by,
        "created_at": release.created_at.isoformat(),
        "canary_started_at": release.canary_started_at.isoformat() if release.canary_started_at else None,
        "decided_at": release.decided_at.isoformat() if release.decided_at else None,
        "canary": {"runs": canary.runs, "failed": canary.failed, "failure_rate": round(canary.failure_rate, 4)},
        "control": {"runs": control.runs, "failed": control.failed, "failure_rate": round(control.failure_rate, 4)},
        "min_runs": settings.release_canary_min_runs,
    }


@router.get("")
async def list_releases(principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    rows = (await session.scalars(select(Release).order_by(Release.created_at.desc()).limit(HISTORY))).all()
    return {"can_manage": principal.is_admin, "releases": [await _view(session, r) for r in rows]}


@router.get("/{release_id}")
async def get_release(release_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    release = await session.get(Release, _uuid(release_id))
    if release is None:
        raise ApiError(404, "not_found", "Not found.")
    return await _view(session, release)


@router.post("/{release_id}/evaluate")
async def evaluate(release_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    """Compare the canary with the others now and act on the verdict (admins)."""
    _admin(principal)
    release = await session.get(Release, _uuid(release_id), with_for_update=True)
    if release is None:
        raise ApiError(404, "not_found", "Not found.")
    verdict = await releases.evaluate(session, release)
    await session.commit()
    return {**await _view(session, release), "verdict": verdict.model_dump()}


@router.post("/{release_id}/approve")
async def approve(release_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    _admin(principal)
    try:
        release = await releases.approve(session, _uuid(release_id), principal.user_id)
    except releases.ReleaseError as exc:
        raise _error(exc) from exc
    await session.commit()
    return await _view(session, release)


@router.post("/{release_id}/rollback")
async def rollback(release_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    _admin(principal)
    try:
        release = await releases.rollback(session, _uuid(release_id), principal.user_id)
    except releases.ReleaseError as exc:
        raise _error(exc) from exc
    await session.commit()
    return await _view(session, release)
