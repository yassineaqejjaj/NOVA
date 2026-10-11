"""Policies applied to executions: the lessons each specialist agent learned from FORGE (docs/TRAINING.md)."""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.domain.agents import AgentProfile
from nova.domain.learning import AgentLearning
from nova.domain.release import in_canary
from nova.infra.db import utcnow
from nova.infra.models import AgentPolicy, Release

ACTIVE_CACHE_SECONDS = 30.0
_cache: tuple[float, dict[str, Any], list[dict[str, Any]]] | None = None


def invalidate() -> None:
    global _cache
    _cache = None


def learning(policy: AgentPolicy, release_id: str | None = None, canary: bool = False) -> AgentLearning:
    return AgentLearning(
        policy_id=str(policy.id),
        version=policy.version,
        release_id=release_id,
        canary=canary,
        standards=list(policy.standards),
        skills=dict(policy.skills),
    )


async def active_policies(session: AsyncSession) -> dict[str, AgentPolicy]:
    # The SDLC agent's policy (agent "sdlc") has its own lifecycle (services/sdlc_improvement.py)
    rows = (await session.scalars(select(AgentPolicy).where(AgentPolicy.status == "active", AgentPolicy.agent != "sdlc"))).all()
    return {p.agent: p for p in rows}


async def _canaries(session: AsyncSession) -> list[dict[str, Any]]:
    """Running canary releases: ``{release_id, agent, percent, learning}`` (the candidate's lessons)."""
    rows = (
        await session.execute(
            select(Release, AgentPolicy)
            .join(AgentPolicy, AgentPolicy.id == Release.policy_id)
            .where(Release.status.in_(("canary", "awaiting_approval")), Release.canary_percent > 0, Release.agent != "sdlc")
        )
    ).all()
    return [
        {
            "release_id": str(r.id),
            "agent": r.agent,
            "percent": r.canary_percent,
            "learning": learning(p, release_id=str(r.id), canary=True).model_dump(),
        }
        for r, p in rows
    ]


async def snapshot(session: AsyncSession, policy_id: str | None = None, user_id: str | None = None) -> dict[str, Any]:
    """Lessons applied to one execution: the active policy of every agent, or ``policy_id`` for its agent.

    With a ``user_id`` (production traffic), a user inside a running canary's stable share gets the candidate's
    lessons for that agent. The snapshot is stored in the execution state, so a resumed or retried execution
    keeps the lessons it started with even if a policy is promoted meanwhile (reproducibility).
    """
    global _cache
    if _cache and time.monotonic() - _cache[0] < ACTIVE_CACHE_SECONDS:
        active, canaries = dict(_cache[1]), _cache[2]
    else:
        released = {
            r.policy_id: str(r.id) for r in (await session.scalars(select(Release).where(Release.status == "active"))).all()
        }
        active = {
            agent: learning(p, release_id=released.get(p.id)).model_dump()
            for agent, p in (await active_policies(session)).items()
        }
        canaries = await _canaries(session)
        _cache = (time.monotonic(), active, canaries)
        active = dict(active)
    if user_id:
        for canary in canaries:
            if in_canary(canary["release_id"], user_id, canary["percent"]):
                active[canary["agent"]] = canary["learning"]
    if policy_id:
        try:
            policy = await session.get(AgentPolicy, uuid.UUID(str(policy_id)))
        except ValueError:
            policy = None
        if policy is not None:
            active[policy.agent] = learning(policy).model_dump()
    return active


async def ensure_base_policy(session: AsyncSession, profile: AgentProfile) -> AgentPolicy:
    """The active policy of the agent; the first one (v0, no lessons) is created on the first training cycle."""
    active = await session.scalar(select(AgentPolicy).where(AgentPolicy.agent == profile.value, AgentPolicy.status == "active"))
    if active is not None:
        return active
    policy = AgentPolicy(
        agent=profile.value,
        version=await next_version(session, profile),
        status="active",
        summary="Version de départ : standards et instructions des compétences, sans leçon apprise.",
        activated_at=utcnow(),
    )
    session.add(policy)
    await session.flush()
    invalidate()
    return policy


async def next_version(session: AsyncSession, profile: AgentProfile) -> int:
    current = await session.scalar(select(func.max(AgentPolicy.version)).where(AgentPolicy.agent == profile.value))
    return 0 if current is None else int(current) + 1


async def activate(session: AsyncSession, policy: AgentPolicy) -> AgentPolicy | None:
    """Make ``policy`` the agent's active policy; returns the policy it replaces (retired)."""
    previous = await session.scalar(
        select(AgentPolicy).where(AgentPolicy.agent == policy.agent, AgentPolicy.status == "active", AgentPolicy.id != policy.id)
    )
    now = utcnow()
    if previous is not None:
        previous.status = "retired"
        previous.retired_at = now
    policy.status = "active"
    policy.activated_at = now
    policy.retired_at = None
    await session.flush()
    invalidate()
    return previous


def release_of(snapshot: dict[str, Any]) -> str | None:
    """The release a snapshot was served under: a canary the user is in first, else the active release."""
    entries = [v for v in snapshot.values() if isinstance(v, dict) and v.get("release_id")]
    chosen = next((v for v in entries if v.get("canary")), entries[0] if entries else None)
    return chosen["release_id"] if chosen else None
