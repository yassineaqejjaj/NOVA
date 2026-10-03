"""Helpers shared by graph nodes: spans, guarded failures, progress and plan blocks."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.runtime import Runtime
from opentelemetry import trace

from nova.agent.deps import AgentDeps
from nova.domain.blocks import Block, ProgressLine
from nova.domain.enums import BlockType, NovaPhase
from nova.domain.llm import LLMError
from nova.domain.state import ExecutionError, NovaState

tracer = trace.get_tracer("nova.agent")

NodeFn = Callable[[NovaState, Runtime[AgentDeps]], Awaitable[dict[str, Any]]]


class NodeFailure(Exception):
    """Non-retryable failure of a node (the execution ends as failed, completed work is kept)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ExecutionPaused(Exception):
    """Raised at a node boundary when the user paused the execution (not retried by the RetryPolicy)."""


def node(name: str) -> Callable[[NodeFn], NodeFn]:
    """Span per node; converts non-retryable failures into state errors (retryable ones are re-raised
    so that LangGraph's RetryPolicy, then Celery, can retry from the last checkpoint)."""

    def decorator(fn: NodeFn) -> NodeFn:
        @functools.wraps(fn)
        async def wrapper(state: NovaState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
            with tracer.start_as_current_span(f"nova.{name}") as span:
                span.set_attribute("nova.node", name)
                span.set_attribute("nova.task_id", state.task_id)
                if (
                    name not in ("finalize", "emit_forge_trace")
                    and state.status == "running"
                    and await runtime.context.store.is_cancelled(state.task_id)
                ):
                    return {"status": "cancelled"}  # cooperative cancellation at node boundaries
                if (
                    name not in ("finalize", "emit_forge_trace")
                    and state.status == "running"
                    and await runtime.context.store.is_paused(state.task_id)
                ):
                    # Stop before this node: the last checkpoint is kept and the run resumes from here.
                    raise ExecutionPaused(state.task_id)
                try:
                    return await fn(state, runtime)
                except LLMError as exc:
                    if exc.retryable:
                        raise
                    return _failed(state, name, "model_error", str(exc))
                except NodeFailure as exc:
                    span.set_attribute("error.type", exc.code)
                    return _failed(state, name, exc.code, exc.message)

        return wrapper

    return decorator


def _failed(state: NovaState, node_name: str, code: str, message: str) -> dict[str, Any]:
    return {
        "errors": [*state.errors, ExecutionError(node=node_name, code=code, message=message)],
        "status": "failed",
        "phase": NovaPhase.failed,
    }


def deps(runtime: Runtime[AgentDeps]) -> AgentDeps:
    return runtime.context


async def set_phase(d: AgentDeps, state: NovaState, phase: NovaPhase, label: str) -> None:
    await d.store.set_phase(state.task_id, phase, label)


async def progress(d: AgentDeps, state: NovaState, key: str, label: str, status: str, detail: str = "") -> None:
    await d.store.progress(state.task_id, state.message_id, ProgressLine(key=key, label=label, status=status, detail=detail))


async def upsert(d: AgentDeps, state: NovaState, block: Block) -> None:
    await d.store.upsert_block(state.task_id, state.message_id, block)


def plan_block(state: NovaState, d: AgentDeps) -> Block:
    plan = state.plan
    assert plan is not None
    steps = []
    for s in plan.steps:
        skill_name = d.skills.get(s.skill_id).name if s.skill_id and d.skills.has(s.skill_id) else None
        steps.append({**s.model_dump(mode="json"), "skill_name": skill_name})
    return Block(
        key="plan",
        type=BlockType.plan,
        data={
            "objective": plan.objective,
            "workflow_id": plan.workflow_id,
            "steps": steps,
            "done": plan.done_count,
            "total": len(plan.steps),
            "assumptions": plan.assumptions,
        },
    )
