"""Scheduled jobs: due scheduled work, FORGE evaluation refresh, retention."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete, select

from nova.config import get_settings
from nova.domain.enums import TaskStatus
from nova.domain.evaluation import FeedbackRecord
from nova.domain.outputs import EvaluationReference
from nova.infra import scope
from nova.infra.db import session_scope, utcnow
from nova.infra.models import ContextRetrievalReference, ExecutionEvent, IntegrationReference, Task
from nova.services import forge_outbox, forget, providers
from nova.services.dispatch import dispatch
from nova.services.workspaces import thread_id, workspace_ids

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


async def run_missions() -> int:
    """Minute tick: start due routines and move goals forward (safety net for the task-settled hook)."""
    from nova.services import goals, routines

    async with session_scope() as session:
        ids = await routines.run_due(session)
        ids += await goals.advance_open_goals(session)
    for task_id in ids:
        await dispatch(task_id, "start")
    return len(ids)


async def on_task_settled(task_id: str) -> None:
    """A NOVA execution reached completion, a failure or a question: the goal it serves moves forward."""
    import uuid as _uuid

    from nova.services import goals, releases

    async with session_scope() as session:
        task = await session.get(Task, _uuid.UUID(task_id))
        goal_id = (task.input or {}).get("goal_id") if task is not None and task.origin == "goal" else None
        ids = await goals.advance_open_goals(session, goal_id=_uuid.UUID(goal_id)) if goal_id else []
    try:
        async with session_scope() as session:
            await releases.evaluate_open(session)  # a running canary may have enough runs for a verdict
    except Exception:  # release bookkeeping must never fail the execution that triggered it
        log.exception("Canary evaluation after %s failed", task_id)
    for tid in ids:
        await dispatch(tid, "start")


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


async def process_forge_outbox() -> int:
    """Catch-up pass: captures FORGE could not take (it was down, a worker died) are attempted again when they are due."""
    return await forge_outbox.process_due(providers.evaluation())


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
            if reference.status in ("completed", "failed", "cancelled", "skipped") and not row.data.get("pending_feedback"):
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


async def purge_old_checkpoints(limit: int = 200) -> int:
    """Delete the LangGraph checkpoint of finished runs older than ``NOVA_CHECKPOINT_RETENTION_DAYS``.

    A checkpoint carries the whole context of a run (items, step outputs): past the retention it can no longer be
    resumed, retried or re-read (feedback regression). Each run is marked so it is not purged twice.
    """
    days = get_settings().checkpoint_retention_days
    if not days:
        return 0
    cutoff = utcnow() - timedelta(days=days)
    purged = 0
    async with session_scope() as session:
        rows = (
            await session.scalars(
                select(Task)
                .where(Task.status.in_(("completed", "failed", "cancelled")), Task.finished_at < cutoff)
                .order_by(Task.finished_at)
                .limit(limit * 4)
            )
        ).all()
        todo = [t for t in rows if not (t.input or {}).get("checkpoint_purged_at")][:limit]
        if todo:
            from nova.agent.runtime import open_checkpointer

            async with open_checkpointer(get_settings().database_url) as saver:
                for task in todo:
                    await saver.adelete_thread(thread_id(task.id, task.workspace_id))
                    task.input = {**(task.input or {}), "checkpoint_purged_at": utcnow().isoformat()}
                    purged += 1
    forget.count_purged("checkpoints", purged)
    return purged


async def apply_retention() -> dict[str, int]:
    """Retention. With ``NOVA_WORKSPACE_ENFORCEMENT=enforce`` it runs workspace by workspace (each under its own scope,
    so a job can never delete across workspaces); otherwise in one pass, as before."""
    if scope.mode() != "enforce":
        return await _retain()
    total: dict[str, int] = {}
    with scope.platform_scope():  # which workspaces exist is not a question about one of them
        async with session_scope() as session:
            known = set(await workspace_ids(session))
            for model in (Task, ContextRetrievalReference, ExecutionEvent):  # rows of an unregistered workspace still age out
                known |= set((await session.scalars(select(model.workspace_id).distinct())).all())
    for workspace in sorted(known):
        with scope.workspace_scope(workspace):
            for key, value in (await _retain()).items():
                total[key] = total.get(key, 0) + value
    return total or {"context_references": 0, "execution_events": 0, "checkpoints": 0}


async def _retain() -> dict[str, int]:
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
    checkpoints = await purge_old_checkpoints()
    forget.count_purged("context_references", refs.rowcount or 0)
    forget.count_purged("execution_events", events.rowcount or 0)
    return {
        "context_references": refs.rowcount or 0,
        "execution_events": events.rowcount or 0,
        "checkpoints": checkpoints,
    }
