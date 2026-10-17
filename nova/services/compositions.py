"""Which Skill compositions worked for a kind of request: the history planning leans on (domain/assembly.py)."""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.domain.assembly import composition_bonuses
from nova.domain.release import TRAFFIC_ORIGINS
from nova.infra.models import Task
from nova.services.workspaces import cache_key

HISTORY = 400  # most recent final production executions examined
CACHE_SECONDS = 60.0
_cache: dict[tuple, tuple[float, dict[str, float]]] = {}  # (workspace, category): never served across workspaces


def invalidate() -> None:
    _cache.clear()


async def priors(session: AsyncSession, category: str) -> dict[str, float]:
    """Router bonuses per Skill for requests of ``category``, from past executions' manifests."""
    key = cache_key(category)
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return dict(cached[1])
    rows = (
        await session.scalars(
            select(Task)
            .where(Task.status.in_(("completed", "failed")), Task.origin.in_(TRAFFIC_ORIGINS), Task.run_manifest.is_not(None))
            .order_by(Task.created_at.desc())
            .limit(HISTORY)
        )
    ).all()
    history = [
        (tuple(s["skill_id"] for s in manifest.get("skills") or []), task.status == "completed")
        for task in rows
        if (manifest := task.run_manifest or {}).get("category") == category
    ]
    bonuses = composition_bonuses(history)
    _cache[key] = (time.monotonic(), bonuses)
    return dict(bonuses)
