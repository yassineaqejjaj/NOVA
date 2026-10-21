"""Run NOVA executions (called by the Celery worker; eager in tests)."""

from __future__ import annotations

import logging
import uuid
from contextlib import nullcontext
from typing import Any, Literal

from opentelemetry import context as otel_context
from opentelemetry.propagate import extract
from sqlalchemy import select, update

from nova.agent.deps import AgentDeps
from nova.agent.nodes.common import ExecutionPaused
from nova.agent.providers.budget import BudgetedProvider, BudgetExceeded, tightest
from nova.agent.providers.factory import build_llm_provider
from nova.agent.providers.fallback import FallbackProvider, fallback_breakers
from nova.agent.providers.recording import RecordingProvider
from nova.agent.runtime import AgentRuntime, open_checkpointer
from nova.agent.tools.registry import get_tool_registry
from nova.artifacts.registry import get_artifact_registry
from nova.config import get_settings
from nova.domain.blocks import error_block
from nova.domain.context import ContextError
from nova.domain.enums import EventType, ExecutionOrigin, NovaPhase, TaskStatus
from nova.domain.llm import LLMError
from nova.domain.llm_guardrail import CallScope
from nova.domain.manifest import manifest_from_state
from nova.domain.pricing import Pricing
from nova.domain.release import TRAFFIC_ORIGINS
from nova.domain.state import NovaState
from nova.infra.db import session_scope, utcnow
from nova.infra.events import get_publisher
from nova.infra.models import ContextRetrievalReference, Task, WorkflowExecution
from nova.infra.scope import platform_scope, workspace_scope
from nova.services import compositions, learning, llm_calls, llm_config, llm_guard, providers, skill_scores, workspaces
from nova.services.access import effective_permissions
from nova.services.execution_store import SqlExecutionStore, emit_event
from nova.services.users import get_user, resolve_principal
from nova.services.workspaces import thread_id
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


async def build_deps(
    principal_user_id: str,
    project_id: uuid.UUID | None,
    origin: str,
    task_id: str | None = None,
    model_override: str | None = None,
    run_budget: dict[str, Any] | None = None,
) -> AgentDeps:
    """The ports of one execution. With a ``task_id`` every model call is recorded (tokens, cost, latency).

    ``run_budget`` (``max_tokens``, ``max_cost``) is a cap the caller asks for (FORGE): the tighter of it and NOVA's own applies.
    """
    async with session_scope() as session:
        user = await get_user(session, principal_user_id)
        assert user is not None
        principal = await resolve_principal(session, user)
        permissions = await effective_permissions(session, principal, project_id)
    async with session_scope() as session:
        scores = await skill_scores.latest(session)
    settings = get_settings()
    org_llm = providers.llm()
    llm = org_llm if origin == ExecutionOrigin.forge_protocol else await providers.llm_for_user(principal_user_id)
    pricing = Pricing(settings.llm_price_input_per_mtok, settings.llm_price_output_per_mtok, settings.llm_price_table)

    uses_org_model = llm is org_llm  # false for a user's own key (bring your own model): their data stays where they chose
    # What this run has read (context, extracts, Artifacts) caps where its model calls may go (domain/llm_guardrail.py)
    scope = CallScope()
    destination = (
        llm_guard.org_destination(settings)
        if uses_org_model or model_override
        else (await llm_config.destination_for_user(principal_user_id)) or llm_guard.org_destination(settings)
    )

    def recorded(provider: Any) -> Any:  # every attempt is recorded, including the failed ones that trigger a fallback
        return RecordingProvider(provider, llm_calls.recorder_for(task_id), pricing) if task_id else provider

    if model_override:  # replay: the organization's provider with another (allow-listed) model; no personal key
        llm = recorded(build_llm_provider(settings.model_copy(update={"llm_model": model_override})))
    elif settings.llm_fallback_models and uses_org_model:
        chain = [
            org_llm,
            *(build_llm_provider(settings.model_copy(update={"llm_model": m})) for m in settings.llm_fallback_models),
        ]
        llm = FallbackProvider([recorded(p) for p in chain], fallback_breakers(chain, settings))
    else:
        llm = recorded(llm)
    skill_llms: dict[str, Any] = {}
    if uses_org_model and not model_override:  # routing only ever uses the organization's models
        allowed = {settings.llm_model, *settings.llm_fallback_models, *settings.replay_models}
        for skill_id, model in settings.llm_skill_models.items():
            if model in allowed:
                skill_llms[skill_id] = recorded(build_llm_provider(settings.model_copy(update={"llm_model": model})))
            else:
                log.warning("Model %s routed to Skill %s is not an allowed model: ignored", model, skill_id)
    limits = {
        "run_cost_budget_usd": tightest(settings.run_cost_budget_usd, (run_budget or {}).get("max_cost")),
        "run_token_budget": int(tightest(settings.run_token_budget, (run_budget or {}).get("max_tokens"))),
    }
    if task_id and (any(limits.values()) or settings.user_daily_cost_budget_usd):
        check = llm_calls.budget_check(task_id, principal_user_id, settings.model_copy(update=limits))
        llm = BudgetedProvider(llm, check)
        skill_llms = {k: BudgetedProvider(v, check) for k, v in skill_llms.items()}
    # Outermost: a refused call is neither budgeted nor recorded, and nothing is sent (explicit error, audit event)
    llm = llm_guard.guard(llm, scope, destination, settings=settings, task_id=task_id, user_id=principal_user_id)
    skill_llms = {
        k: llm_guard.guard(v, scope, destination, settings=settings, task_id=task_id, user_id=principal_user_id)
        for k, v in skill_llms.items()
    }
    return AgentDeps(
        settings=settings,
        llm=llm,
        skill_llms=skill_llms,
        skill_scores=scores,
        composition_priors=_composition_priors,
        context=providers.context(),
        skills=get_skill_registry(),
        artifacts=get_artifact_registry(),
        tools=get_tool_registry(),
        store=SqlExecutionStore(principal, scope=scope),
        design=providers.design(),
        evaluation=None if origin == ExecutionOrigin.forge_protocol else providers.evaluation(),
        permissions=permissions,
        scope=scope,
    )


async def _composition_priors(category: str) -> dict[str, float]:
    async with session_scope() as session:
        return await compositions.priors(session, category)


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
            update(WorkflowExecution)
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
    """Run one segment of an execution (until completion or the next interrupt), then let missions move forward.

    Everything the run reads or writes is scoped to the workspace of its task (NOVA_WORKSPACE_ENFORCEMENT), whoever
    started it: the API request that is still running, or a worker that has no request at all.
    """
    with _task_scope(await _workspace_of(task_id)):
        status = await _run_segment(task_id, mode, resume_value, traceparent=traceparent, final_attempt=final_attempt)
        if status in (TaskStatus.completed, TaskStatus.failed, TaskStatus.waiting_user, TaskStatus.cancelled):
            from nova.services.maintenance import on_task_settled

            try:
                await on_task_settled(task_id)
            except Exception:  # a goal bookkeeping problem must never fail the execution itself
                log.exception("Mission update after %s failed", task_id)
        return status


async def _workspace_of(task_id: str) -> uuid.UUID | None:
    """The workspace of a task, read without any scope (the caller already holds the right to run it)."""
    if not workspaces.enabled():
        return None
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        return None
    with platform_scope():
        async with session_scope() as session:
            return await session.scalar(select(Task.workspace_id).where(Task.id == tid))


def _task_scope(workspace_id: uuid.UUID | None) -> Any:
    return workspace_scope(workspace_id) if workspace_id is not None else nullcontext()


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
        workspace_id = task.workspace_id
        if await session.scalar(select(WorkflowExecution).where(WorkflowExecution.task_id == tid)) is None:
            session.add(WorkflowExecution(task_id=tid, thread_id=thread_id(task_id, workspace_id), workspace_id=workspace_id))
        user_id, project_id, origin, initial_input = str(task.user_id), task.project_id, task.origin, dict(task.input)
        if mode != "resume" and "learning" not in initial_input:
            # Lessons the agents learned from FORGE, frozen for the whole execution (services/learning.py)
            initial_input["learning"] = await learning.snapshot(
                session, initial_input.get("learning_policy_id"), user_id=user_id if origin in TRAFFIC_ORIGINS else None
            )
            served = learning.release_of(initial_input["learning"])
            task.release_id = uuid.UUID(served) if served else None  # lets a release be compared with the rest
            task.input = {**task.input, "learning": initial_input["learning"]}  # kept for retries and FORGE metadata
        if "started_at" not in initial_input:
            initial_input["started_at"] = utcnow().isoformat()
            task.input = {**task.input, "started_at": initial_input["started_at"]}  # kept for retries and FORGE capture
        initial_input.pop("learning_policy_id", None)
        message_id = str(task.message_id) if task.message_id else None
        await emit_event(session, get_publisher(), tid, EventType.task, {"status": "running"})

    deps = await build_deps(
        user_id,
        project_id,
        origin,
        task_id,
        model_override=initial_input.get("model_override"),
        run_budget=initial_input.get("run_budget"),
    )
    parent = extract(traceparent) if traceparent else otel_context.get_current()
    settings = get_settings()
    try:
        async with open_checkpointer(settings.database_url) as checkpointer:
            runtime = AgentRuntime(checkpointer, workspace_id)
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
            usage={**state.usage.model_dump(), **await llm_calls.totals(task_id)},
            **await _manifest_values(state, initial_input),
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
        usage={**state.usage.model_dump(), **await llm_calls.totals(task_id)},
        error=state.errors[-1].message if state.errors and status == TaskStatus.failed else None,
        phase=state.phase.value,
        **await _manifest_values(state, initial_input),
    )
    return status


async def _manifest_values(state: NovaState, initial_input: dict[str, Any]) -> dict[str, Any]:
    """``run_manifest`` as keyword values for ``_set_status``; empty when it could not be built (keeps an earlier one)."""
    manifest = await _manifest_for(state, initial_input)
    return {"run_manifest": manifest} if manifest else {}


async def _manifest_for(state: NovaState, initial_input: dict[str, Any]) -> dict[str, Any] | None:
    """The run manifest of this segment. Best effort: bookkeeping must never change an execution's outcome."""
    try:
        snapshot_name, snapshot_version = None, None
        if state.context_reference_id:
            async with session_scope() as session:
                ref = await session.get(ContextRetrievalReference, uuid.UUID(state.context_reference_id))
                if ref is not None:
                    snapshot_name, snapshot_version = ref.snapshot_name, ref.snapshot_version
        settings = get_settings()
        manifest = manifest_from_state(
            state,
            agent_version=settings.version,
            token_budget=settings.orbit_default_token_budget,
            snapshot_name=snapshot_name,
            snapshot_version=snapshot_version,
            ids=initial_input.get("manifest_ids"),
            overrides=initial_input.get("replay_overrides"),
        )
        return manifest.model_dump(mode="json")
    except Exception:
        log.warning("Run manifest for %s could not be built", state.task_id, exc_info=True)
        return None


def _friendly(exc: Exception) -> str:
    if isinstance(exc, BudgetExceeded):
        return f"{exc.message} NOVA stopped before spending more; completed steps were kept."
    if isinstance(exc, LLMError):
        log.warning("Execution failed on the inference server: %s (retryable=%s)", exc, exc.retryable)
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
