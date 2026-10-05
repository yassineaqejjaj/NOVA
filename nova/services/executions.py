"""Run NOVA executions (called by the Celery worker; eager in tests)."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from opentelemetry import context as otel_context
from opentelemetry.propagate import extract
from sqlalchemy import select

from nova.agent.deps import AgentDeps
from nova.agent.nodes.common import ExecutionPaused
from nova.agent.runtime import AgentRuntime, open_checkpointer
from nova.agent.tools.registry import get_tool_registry
from nova.artifacts.registry import get_artifact_registry
from nova.config import get_settings
from nova.domain.blocks import error_block
from nova.domain.context import ContextError
from nova.domain.enums import EventType, ExecutionOrigin, NovaPhase, TaskStatus
from nova.domain.llm import LLMError
from nova.domain.state import NovaState
from nova.infra.db import session_scope, utcnow
from nova.infra.events import get_publisher
from nova.infra.models import Task, WorkflowExecution
from nova.services import providers
from nova.services.access import effective_permissions
from nova.services.execution_store import SqlExecutionStore, emit_event
from nova.services.users import get_user, principal_for
from nova.skills.registry import get_skill_registry

log = logging.getLogger(__name__)

STATE_TO_STATUS = {
    "completed": TaskStatus.completed,
    "failed": TaskStatus.failed,
    "cancelled": TaskStatus.cancelled,
    "running": TaskStatus.running,
    "waiting_user": TaskStatus.waiting_user,
}


class RetryableExecutionError(Exception):
    """Infrastructure failure: the worker retries the task from its last checkpoint."""


async def build_deps(principal_user_id: str, project_id: uuid.UUID | None, origin: str) -> AgentDeps:
    async with session_scope() as session:
        user = await get_user(session, principal_user_id)
        assert user is not None
        principal = principal_for(user)
        permissions = await effective_permissions(session, principal, project_id)
    return AgentDeps(
        settings=get_settings(),
        llm=providers.llm(),
        context=providers.context(),
        skills=get_skill_registry(),
        artifacts=get_artifact_registry(),
        tools=get_tool_registry(),
        store=SqlExecutionStore(principal),
        evaluation=None if origin == ExecutionOrigin.forge_protocol else providers.evaluation(),
        permissions=permissions,
    )


async def _set_status(task_id: uuid.UUID, status: TaskStatus, **values: Any) -> None:
    async with session_scope() as session:
        task = await session.get(Task, task_id)
        if task is None:
            return
        task.status = status.value
        for key, value in values.items():
            setattr(task, key, value)
        if status in (TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled):
            task.finished_at = utcnow()
            task.waiting_for = None
        await session.execute(
            WorkflowExecution.__table__.update()
            .where(WorkflowExecution.task_id == task_id)
            .values(status=status.value, finished_at=task.finished_at)
        )
        await emit_event(session, get_publisher(), task_id, EventType.task, {"status": status.value})
        if status != TaskStatus.running:
            await emit_event(session, get_publisher(), task_id, EventType.done, {"status": status.value})


async def run_task(
    task_id: str,
    mode: Literal["start", "resume", "retry"],
    resume_value: Any = None,
    *,
    traceparent: dict[str, str] | None = None,
    final_attempt: bool = True,
) -> TaskStatus:
    """Run one segment of an execution (until completion or the next interrupt), then let missions move forward."""
    status = await _run_segment(task_id, mode, resume_value, traceparent=traceparent, final_attempt=final_attempt)
    if status in (TaskStatus.completed, TaskStatus.failed, TaskStatus.waiting_user, TaskStatus.cancelled):
        from nova.services.maintenance import on_task_settled

        try:
            await on_task_settled(task_id)
        except Exception:  # a goal bookkeeping problem must never fail the execution itself
            log.exception("Mission update after %s failed", task_id)
    return status


async def _run_segment(
    task_id: str,
    mode: Literal["start", "resume", "retry"],
    resume_value: Any = None,
    *,
    traceparent: dict[str, str] | None = None,
    final_attempt: bool = True,
) -> TaskStatus:
    tid = uuid.UUID(task_id)
    async with session_scope() as session:
        task = await session.get(Task, tid)
        if task is None:
            return TaskStatus.failed
        if mode == "start" and task.status not in (TaskStatus.queued, TaskStatus.scheduled):
            return TaskStatus(task.status)
        if mode == "resume" and (task.status not in (TaskStatus.waiting_user, TaskStatus.queued) or not task.waiting_for):
            return TaskStatus(task.status)
        task.status = TaskStatus.running.value
        task.started_at = task.started_at or utcnow()
        task.waiting_for = None
        if await session.scalar(select(WorkflowExecution).where(WorkflowExecution.task_id == tid)) is None:
            session.add(WorkflowExecution(task_id=tid, thread_id=task_id))
        user_id, project_id, origin, initial_input = str(task.user_id), task.project_id, task.origin, dict(task.input)
        message_id = str(task.message_id) if task.message_id else None
        await emit_event(session, get_publisher(), tid, EventType.task, {"status": "running"})

    deps = await build_deps(user_id, project_id, origin)
    parent = extract(traceparent) if traceparent else otel_context.get_current()
    settings = get_settings()
    try:
        async with open_checkpointer(settings.database_url) as checkpointer:
            runtime = AgentRuntime(checkpointer)
            if mode == "start":
                initial = NovaState.model_validate({**initial_input, "task_id": task_id, "user_id": user_id})
                outcome = await runtime.run(task_id, deps, initial=initial, parent=parent)
            elif mode == "resume":
                outcome = await runtime.run(task_id, deps, resume=resume_value, parent=parent)
            elif await runtime.has_checkpoint(task_id):
                outcome = await runtime.run(task_id, deps, retry=True, parent=parent)
            else:  # failed before the first checkpoint: start again
                initial = NovaState.model_validate({**initial_input, "task_id": task_id, "user_id": user_id})
                outcome = await runtime.run(task_id, deps, initial=initial, parent=parent)
    except ExecutionPaused:
        await _set_status(tid, TaskStatus.paused, phase=NovaPhase.waiting_user.value)
        return TaskStatus.paused
    except (LLMError, ContextError, ConnectionError, TimeoutError, OSError) as exc:
        retryable = getattr(exc, "retryable", True)
        if retryable and not final_attempt:
            raise RetryableExecutionError(str(exc)) from exc
        await _fail(tid, message_id, deps, _friendly(exc))
        return TaskStatus.failed
    except Exception:
        log.exception("Execution %s failed", task_id)
        await _fail(tid, message_id, deps, "An unexpected error interrupted NOVA. Completed steps were kept.")
        return TaskStatus.failed

    state = outcome.state
    if outcome.waiting_for is not None:
        await _set_status(
            tid,
            TaskStatus.waiting_user,
            waiting_for=outcome.waiting_for,
            phase=NovaPhase.waiting_user.value,
            trace_id=state.trace_id,
            model=state.model,
            usage=state.usage.model_dump(),
        )
        return TaskStatus.waiting_user
    status = STATE_TO_STATUS.get(state.status, TaskStatus.completed)
    if status == TaskStatus.running:
        status = TaskStatus.completed
    await _set_status(
        tid,
        status,
        trace_id=state.trace_id,
        model=state.model,
        usage=state.usage.model_dump(),
        error=state.errors[-1].message if state.errors and status == TaskStatus.failed else None,
        phase=state.phase.value,
    )
    return status


def _friendly(exc: Exception) -> str:
    if isinstance(exc, LLMError):
        return "The inference server did not respond correctly. You can retry: NOVA resumes from the last completed step."
    if isinstance(exc, ContextError):
        return f"ORBIT could not be reached ({exc.message}). You can retry."
    return "A service NOVA depends on is unavailable. You can retry: completed steps are kept."


async def _fail(task_id: uuid.UUID, message_id: str | None, deps: AgentDeps, message: str) -> None:
    await deps.store.upsert_block(
        str(task_id), message_id, error_block("NOVA couldn't finish this task", message, [{"label": "Retry", "action": "retry"}])
    )
    await deps.store.set_phase(str(task_id), NovaPhase.failed, "Failed")
    await _set_status(task_id, TaskStatus.failed, error=message, phase=NovaPhase.failed.value)
