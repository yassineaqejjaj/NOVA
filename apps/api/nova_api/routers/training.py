"""FORGE training loop of the specialist agents (docs/TRAINING.md): status for everyone, actions for admins."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.config import get_settings
from nova.domain.agents import AGENTS, AgentProfile
from nova.infra.db import get_session
from nova.infra.models import AgentPolicy, TrainingCycle
from nova.services import training
from nova.skills.registry import get_skill_registry
from nova_api.auth import CurrentPrincipal
from nova_api.errors import ApiError

router = APIRouter(prefix="/training", tags=["training"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
HISTORY = 20


def _profile(agent: str) -> AgentProfile:
    if agent not in AgentProfile.__members__:
        raise ApiError(404, "not_found", "Unknown agent.")
    return AgentProfile(agent)


def _admin(principal: Any) -> None:
    if not principal.is_admin:
        raise ApiError(403, "forbidden", "Only an administrator can train NOVA's agents.")


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ApiError(404, "not_found", "Not found.") from exc


def _error(exc: training.TrainingError) -> ApiError:
    status = {"not_found": 404, "conflict": 409, "not_configured": 409}.get(exc.code, 422)
    return ApiError(status, exc.code, exc.message)


def _forge_url(path: str) -> str:
    return f"{get_settings().forge_public_url.rstrip('/')}{path}"


def policy_view(policy: AgentPolicy | None, *, detail: bool = False) -> dict[str, Any] | None:
    if policy is None:
        return None
    view: dict[str, Any] = {
        "id": str(policy.id),
        "version": policy.version,
        "status": policy.status,
        "summary": policy.summary,
        "score": policy.score,
        "standards_count": len(policy.standards),
        "lessons_count": sum(len(v) for v in policy.skills.values()),
        "skills_with_lessons": len(policy.skills),
        "created_at": policy.created_at.isoformat(),
        "activated_at": policy.activated_at.isoformat() if policy.activated_at else None,
        "parent_id": str(policy.parent_id) if policy.parent_id else None,
    }
    if detail:
        view |= {"standards": policy.standards, "skills": policy.skills, "recommendations": policy.recommendations}
    return view


def cycle_view(cycle: TrainingCycle | None, versions: dict[uuid.UUID, int] | None = None) -> dict[str, Any] | None:
    if cycle is None:
        return None
    versions = versions or {}
    return {
        "id": str(cycle.id),
        "agent": cycle.agent,
        "status": cycle.status,
        "trigger": cycle.trigger,
        "skills_count": len(cycle.skills),
        "runs_count": len(cycle.baseline_runs),
        "baseline_version": versions.get(cycle.baseline_policy_id) if cycle.baseline_policy_id else None,
        "candidate_version": versions.get(cycle.candidate_policy_id) if cycle.candidate_policy_id else None,
        "experiment_url": _forge_url(f"/experiments/{cycle.forge_experiment_id}") if cycle.forge_experiment_id else None,
        "result": cycle.result,
        "error": cycle.error,
        "created_at": cycle.created_at.isoformat(),
        "finished_at": cycle.finished_at.isoformat() if cycle.finished_at else None,
    }


async def _versions(session: AsyncSession) -> dict[uuid.UUID, int]:
    return {pid: v for pid, v in (await session.execute(select(AgentPolicy.id, AgentPolicy.version))).all()}


@router.get("")
async def overview(principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    settings = get_settings()
    registry = get_skill_registry()
    versions = await _versions(session)
    agents = []
    for profile in AgentProfile:
        active = await session.scalar(
            select(AgentPolicy).where(AgentPolicy.agent == profile.value, AgentPolicy.status == "active")
        )
        last = await session.scalar(
            select(TrainingCycle).where(TrainingCycle.agent == profile.value).order_by(TrainingCycle.created_at.desc()).limit(1)
        )
        agents.append(
            {
                "agent": profile.value,
                "name": AGENTS[profile].name,
                "skills_count": len(training.agent_skills(registry, profile)),
                "active": policy_view(active),
                "last_cycle": cycle_view(last, versions),
                "training": bool(last and last.status in training.OPEN_STATUSES),
            }
        )
    return {
        "missing": training.missing_configuration(settings),
        "auto_promote": settings.training_auto_promote,
        "interval_days": settings.training_interval_days,
        "repetitions": settings.training_repetitions,
        "forge_url": settings.forge_public_url,
        "can_manage": principal.is_admin,
        "agents": agents,
    }


@router.get("/agents/{agent}")
async def agent_detail(agent: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    profile = _profile(agent)
    registry = get_skill_registry()
    policies = (
        await session.scalars(
            select(AgentPolicy).where(AgentPolicy.agent == profile.value).order_by(AgentPolicy.version.desc()).limit(HISTORY)
        )
    ).all()
    cycles = (
        await session.scalars(
            select(TrainingCycle)
            .where(TrainingCycle.agent == profile.value)
            .order_by(TrainingCycle.created_at.desc())
            .limit(HISTORY)
        )
    ).all()
    versions = await _versions(session)
    active = next((p for p in policies if p.status == "active"), None)
    last_scores = next((c.result.get("baseline", {}).get("scores") for c in cycles if c.result.get("baseline")), None) or {}
    return {
        "agent": profile.value,
        "name": AGENTS[profile].name,
        "can_manage": principal.is_admin,
        "active": policy_view(active, detail=True),
        "skills": [
            {
                "id": s.id,
                "name": s.name,
                "translations": {lang: {"name": t.get("name")} for lang, t in s.translations.items()},
                "lessons": (active.skills.get(s.id, []) if active else []),
                "score": last_scores.get(s.id),
            }
            for s in training.agent_skills(registry, profile)
        ],
        "policies": [policy_view(p, detail=True) for p in policies],
        "cycles": [cycle_view(c, versions) for c in cycles],
    }


@router.post("/agents/{agent}/cycles", status_code=201)
async def start(agent: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    _admin(principal)
    profile = _profile(agent)
    try:
        cycle = await training.start_cycle(session, profile, requested_by=principal.user_id)
    except training.TrainingError as exc:
        raise _error(exc) from exc
    await session.commit()
    return cycle_view(cycle) or {}


@router.post("/cycles", status_code=201)
async def start_all(principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    """One cycle for every agent that is not already training."""
    _admin(principal)
    if missing := training.missing_configuration():
        raise ApiError(409, "not_configured", "Training is not configured: " + ", ".join(missing))
    started = []
    for profile in AgentProfile:
        if await training.open_cycle(session, profile) is None:
            started.append(await training.start_cycle(session, profile, requested_by=principal.user_id))
    await session.commit()
    return {"started": [cycle_view(c) for c in started]}


@router.post("/cycles/{cycle_id}/cancel")
async def cancel(cycle_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    _admin(principal)
    try:
        cycle = await training.cancel(session, _uuid(cycle_id), principal.user_id)
    except training.TrainingError as exc:
        raise _error(exc) from exc
    await session.commit()
    return cycle_view(cycle) or {}


@router.post("/agents/{agent}/rollback")
async def rollback(agent: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    _admin(principal)
    try:
        policy = await training.rollback(session, _profile(agent), principal.user_id)
    except training.TrainingError as exc:
        raise _error(exc) from exc
    await session.commit()
    return policy_view(policy, detail=True) or {}


@router.post("/policies/{policy_id}/activate")
async def activate(policy_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    _admin(principal)
    try:
        policy = await training.promote(session, _uuid(policy_id), principal.user_id)
    except training.TrainingError as exc:
        raise _error(exc) from exc
    await session.commit()
    return policy_view(policy, detail=True) or {}
