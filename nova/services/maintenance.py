"""Scheduled jobs: due scheduled work, FORGE evaluation refresh, retention."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete, select

from nova.config import get_settings
from nova.domain.enums import TaskStatus
from nova.domain.evaluation import FeedbackRecord
from nova.domain.outputs import EvaluationReference
from nova.infra.db import session_scope, utcnow
from nova.infra.models import ContextRetrievalReference, ExecutionEvent, IntegrationReference, Task
from nova.services import providers
from nova.services.dispatch import dispatch

log = logging.getLogger(__name__)


async def start_due_scheduled_tasks() -> int:
    async with session_scope() as session:
        due = (
            await session.scalars(
                select(Task).where(Task.status == TaskStatus.scheduled.value, Task.scheduled_for <= utcnow()).limit(50)
            )
        ).all()
        for task in due:
            task.status = TaskStatus.queued.value
        ids = [str(t.id) for t in due]
    for task_id in ids:
        await dispatch(task_id, "start")
    return len(ids)


async def requeue_stale_tasks(older_than: timedelta = timedelta(minutes=2)) -> int:
    """Re-dispatch tasks still queued (never started) after ``older_than`` — e.g. a lost broker message.

    Safe: ``run_task`` only starts a task that is still queued, and resumes keep their interrupt payload.
    """
    async with session_scope() as session:
        stale = (
            await session.scalars(
                select(Task).where(Task.status == TaskStatus.queued.value, Task.created_at < utcnow() - older_than).limit(50)
            )
        ).all()
        work = [(str(t.id), "resume" if t.waiting_for else ("retry" if t.started_at else "start")) for t in stale]
    for task_id, mode in work:
        if mode == "resume":
            continue  # a resume carries the user's answer in the broker message; it cannot be rebuilt here
        await dispatch(task_id, mode)
    return len(work)


async def refresh_evaluations() -> int:
    """Pull FORGE run status/scores for recent captures and deliver feedback that was waiting for the run."""
    sink = providers.evaluation()
    if sink is None:
        return 0
    refreshed = 0
    async with session_scope() as session:
        rows = (
            await session.scalars(
                select(IntegrationReference).where(
                    IntegrationReference.system == "forge",
                    IntegrationReference.kind == "evaluation",
                    IntegrationReference.updated_at >= utcnow() - timedelta(days=7),
                )
            )
        ).all()
        for row in rows:
            reference = EvaluationReference.model_validate(row.data)
            if reference.status in ("completed", "failed", "cancelled") and not row.data.get("pending_feedback"):
                continue
            try:
                reference = await sink.refresh(reference)
                pending = row.data.get("pending_feedback") or []
                if reference.status in ("completed", "failed") and pending:
                    for fb in pending:
                        await sink.feedback(reference, FeedbackRecord.model_validate(fb))
                    pending = []
                row.data = {**reference.model_dump(mode="json"), "pending_feedback": pending}
                refreshed += 1
            except Exception:
                log.warning("FORGE refresh failed for %s", row.external_id, exc_info=True)
    return refreshed


async def apply_retention() -> dict[str, int]:
    settings = get_settings()
    async with session_scope() as session:
        refs = await session.execute(
            delete(ContextRetrievalReference).where(
                ContextRetrievalReference.created_at < utcnow() - timedelta(days=settings.context_reference_retention_days)
            )
        )
        events = await session.execute(
            delete(ExecutionEvent).where(
                ExecutionEvent.created_at < utcnow() - timedelta(days=settings.execution_event_retention_days)
            )
        )
    return {"context_references": refs.rowcount or 0, "execution_events": events.rowcount or 0}
