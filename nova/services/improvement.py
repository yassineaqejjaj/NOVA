"""The improvement dashboard: what FORGE-validated learning changed, read from what NOVA already stores."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.domain.agents import AGENTS, AgentProfile
from nova.domain.improvement import CyclePoint, PolicyPoint, ReleasePoint, Traffic, agent_progress, headline, traffic_trend
from nova.domain.release import TRAFFIC_ORIGINS
from nova.infra.db import aware, utcnow
from nova.infra.models import AgentPolicy, Release, Task, TrainingCycle

WINDOW_DAYS = 30
FINAL = ("completed", "failed")


async def _traffic(session: AsyncSession, start: Any, end: Any) -> Traffic:
    base = [Task.status.in_(FINAL), Task.origin.in_(TRAFFIC_ORIGINS), Task.created_at >= start, Task.created_at < end]
    runs = await session.scalar(select(func.count(Task.id)).where(*base)) or 0
    failed = await session.scalar(select(func.count(Task.id)).where(*base, Task.status == "failed")) or 0
    return Traffic(runs=int(runs), failed=int(failed))


async def progress(session: AsyncSession) -> dict[str, Any]:
    policies = (await session.scalars(select(AgentPolicy))).all()
    cycles = (await session.scalars(select(TrainingCycle))).all()
    releases = (await session.scalars(select(Release))).all()
    agents: dict[str, dict[str, Any]] = {}
    for profile in AgentProfile:
        name = profile.value
        view = agent_progress(
            [
                PolicyPoint(
                    p.version,
                    p.status,
                    p.score,
                    sum(len(v) for v in p.skills.values()),
                    len(p.standards),
                    aware(p.activated_at or p.created_at),
                )
                for p in policies
                if p.agent == name
            ],
            [
                CyclePoint(
                    c.status,
                    next((p.version for p in policies if p.id == c.baseline_policy_id), None),
                    (c.result.get("baseline") or {}).get("mean"),
                    aware(c.created_at),
                )
                for c in cycles
                if c.agent == name
            ],
            [ReleasePoint(r.status, r.label, r.reason, aware(r.decided_at or r.created_at)) for r in releases if r.agent == name],
        )
        agents[name] = {"agent": name, "name": AGENTS[profile].name, **view}
    now = utcnow()
    window = timedelta(days=WINDOW_DAYS)
    trend = traffic_trend(
        await _traffic(session, now - window, now + timedelta(seconds=1)), await _traffic(session, now - 2 * window, now - window)
    )
    return {"window_days": WINDOW_DAYS, "headline": headline(agents), "agents": list(agents.values()), "traffic": trend}
