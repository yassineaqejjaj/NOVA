"""Policies applied to executions: the lessons each specialist agent learned from FORGE (docs/TRAINING.md)."""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.domain.agents import AgentProfile
from nova.domain.learning import AgentLearning
from nova.infra.db import utcnow
from nova.infra.models import AgentPolicy

ACTIVE_CACHE_SECONDS = 30.0
_active_cache: tuple[float, dict[str, Any]] | None = None


def invalidate() -> None:
    global _active_cache
    _active_cache = None


def learning(policy: AgentPolicy) -> AgentLearning:
    return AgentLearning(
        policy_id=str(policy.id), version=policy.version, standards=list(policy.standards), skills=dict(policy.skills)
    )


async def active_policies(session: AsyncSession) -> dict[str, AgentPolicy]:
    # The SDLC agent's policy (agent "sdlc") has its own lifecycle (services/sdlc_improvement.py)
    rows = (await session.scalars(select(AgentPolicy).where(AgentPolicy.status == "active", AgentPolicy.agent != "sdlc"))).all()
    return {p.agent: p for p in rows}


async def snapshot(session: AsyncSession, policy_id: str | None = None) -> dict[str, Any]:
    """Lessons applied to one execution: the active policy of every agent, or ``policy_id`` for its agent.

    The snapshot is stored in the execution state, so a resumed or retried execution keeps the lessons it
    started with even if a policy is promoted meanwhile (reproducibility).
    """
    global _active_cache
    if _active_cache and time.monotonic() - _active_cache[0] < ACTIVE_CACHE_SECONDS:
        active = dict(_active_cache[1])
    else:
        active = {agent: learning(p).model_dump() for agent, p in (await active_policies(session)).items()}
        _active_cache = (time.monotonic(), active)
        active = dict(active)
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
