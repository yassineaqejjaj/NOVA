"""Per-call model records of a run (``llm_calls``): written by the recording provider, summed per task."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select

from nova.agent.providers.recording import CallRecord, Recorder
from nova.infra.db import session_scope
from nova.infra.models import LLMCall


def recorder_for(task_id: str) -> Recorder:
    tid = uuid.UUID(task_id)

    async def record(rec: CallRecord) -> None:
        async with session_scope() as session:
            seq = (await session.scalar(select(func.coalesce(func.max(LLMCall.seq), 0)).where(LLMCall.task_id == tid))) or 0
            session.add(
                LLMCall(
                    task_id=tid,
                    seq=seq + 1,
                    kind=rec.kind,
                    model=rec.model,
                    input_tokens=rec.usage.input_tokens if rec.usage else None,
                    output_tokens=rec.usage.output_tokens if rec.usage else None,
                    cost_usd=rec.cost_usd,
                    latency_ms=round(rec.latency_ms, 1),
                    status=rec.status,
                    error=rec.error,
                )
            )

    return record


async def totals(task_id: str) -> dict[str, Any]:
    """What a task's model calls added up to: ``{llm_calls, cost_usd, llm_latency_ms}`` (empty when none)."""
    async with session_scope() as session:
        row = (
            await session.execute(
                select(
                    func.count(LLMCall.id),
                    func.coalesce(func.sum(LLMCall.cost_usd), 0.0),
                    func.coalesce(func.sum(LLMCall.latency_ms), 0.0),
                ).where(LLMCall.task_id == uuid.UUID(task_id))
            )
        ).one()
    if not row[0]:
        return {}
    return {"llm_calls": int(row[0]), "cost_usd": round(float(row[1]), 6), "llm_latency_ms": round(float(row[2]), 1)}
