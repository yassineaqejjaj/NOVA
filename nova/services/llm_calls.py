"""Per-call model records of a run (``llm_calls``): written by the recording provider, summed per task."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select

from nova.agent.providers.recording import CallRecord, Recorder
from nova.infra.db import session_scope, utcnow
from nova.infra.models import LLMCall, Task


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


async def spent(task_id: str) -> tuple[float, int]:
    """What a task's model calls have cost so far: ``(cost_usd, tokens)``."""
    async with session_scope() as session:
        row = (
            await session.execute(
                select(
                    func.coalesce(func.sum(LLMCall.cost_usd), 0.0),
                    func.coalesce(func.sum(func.coalesce(LLMCall.input_tokens, 0) + func.coalesce(LLMCall.output_tokens, 0)), 0),
                ).where(LLMCall.task_id == uuid.UUID(task_id))
            )
        ).one()
    return float(row[0]), int(row[1])


async def user_cost_today(user_id: str) -> float:
    """What the user's model calls cost since midnight UTC (all their executions)."""
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    async with session_scope() as session:
        total = await session.scalar(
            select(func.coalesce(func.sum(LLMCall.cost_usd), 0.0))
            .join(Task, Task.id == LLMCall.task_id)
            .where(Task.user_id == uuid.UUID(user_id), LLMCall.created_at >= start)
        )
    return float(total or 0.0)


def budget_check(task_id: str, user_id: str, settings: Any) -> Any:
    """The pre-call check for one execution: raises ``BudgetExceeded`` when a limit is already reached."""
    from nova.agent.providers.budget import BudgetExceeded

    async def check() -> None:
        if settings.run_cost_budget_usd or settings.run_token_budget:
            cost, tokens = await spent(task_id)
            if settings.run_cost_budget_usd and cost >= settings.run_cost_budget_usd:
                raise BudgetExceeded("run", f"This task reached its cost limit (${settings.run_cost_budget_usd:g}).")
            if settings.run_token_budget and tokens >= settings.run_token_budget:
                raise BudgetExceeded("run", f"This task reached its limit of {settings.run_token_budget} tokens.")
        if settings.user_daily_cost_budget_usd and await user_cost_today(user_id) >= settings.user_daily_cost_budget_usd:
            raise BudgetExceeded("user", f"You reached today's usage limit (${settings.user_daily_cost_budget_usd:g}).")

    return check
