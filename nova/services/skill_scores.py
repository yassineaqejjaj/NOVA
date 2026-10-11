"""What FORGE measured per Skill: the latest evaluation of each agent's Skills (training baseline scores)."""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.infra.models import TrainingCycle

CACHE_SECONDS = 60.0
EVALUATED = ("promoted", "validated", "rejected", "no_change")
_cache: tuple[float, dict[str, float]] | None = None


def invalidate() -> None:
    global _cache
    _cache = None


async def latest(session: AsyncSession) -> dict[str, float]:
    """Skill id → FORGE composite score (0-100) from each agent's most recent evaluated cycle."""
    global _cache
    if _cache and time.monotonic() - _cache[0] < CACHE_SECONDS:
        return dict(_cache[1])
    cycles = (
        await session.scalars(
            select(TrainingCycle).where(TrainingCycle.status.in_(EVALUATED)).order_by(TrainingCycle.created_at.desc())
        )
    ).all()
    scores: dict[str, float] = {}
    seen: set[str] = set()
    for cycle in cycles:
        if cycle.agent in seen:
            continue
        measured = ((cycle.result or {}).get("baseline") or {}).get("scores") or {}
        if not measured:
            continue
        seen.add(cycle.agent)
        scores.update({k: float(v) for k, v in measured.items() if isinstance(v, int | float)})
    _cache = (time.monotonic(), scores)
    return dict(scores)
