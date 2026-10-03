"""Run, resume and retry NOVA executions on the LangGraph graph with a checkpointer."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import Command
from opentelemetry import context as otel_context
from opentelemetry import trace

from nova.agent.deps import AgentDeps
from nova.agent.graph import build_graph
from nova.domain.state import NovaState
from nova.infra.redaction import redact

tracer = trace.get_tracer("nova.agent")
RECURSION_LIMIT = 200

_memory_saver: InMemorySaver | None = None


def checkpoint_serde() -> JsonPlusSerializer:
    """Checkpoints may only deserialize NOVA's own domain types (explicit allowlist, no arbitrary classes)."""
    import enum
    import importlib
    import pkgutil

    from pydantic import BaseModel

    import nova.domain

    allowed: list[tuple[str, str]] = []
    for info in pkgutil.iter_modules(nova.domain.__path__, "nova.domain."):
        module = importlib.import_module(info.name)
        for name, value in vars(module).items():
            if isinstance(value, type) and value.__module__ == module.__name__ and issubclass(value, (BaseModel, enum.Enum)):
                allowed.append((module.__name__, name))
    return JsonPlusSerializer(allowed_msgpack_modules=allowed)


def postgres_conn_string(sqlalchemy_url: str) -> str:
    """libpq form of the SQLAlchemy URL for the psycopg checkpointer (asyncpg's ``ssl=`` becomes ``sslmode=``)."""
    url = sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")
    return url.replace("?ssl=", "?sslmode=").replace("&ssl=", "&sslmode=")


@asynccontextmanager
async def open_checkpointer(database_url: str) -> AsyncIterator[Any]:
    """Postgres checkpointer in deployments; in-memory for sqlite-based tests."""
    global _memory_saver
    if database_url.startswith("sqlite"):
        if _memory_saver is None:
            _memory_saver = InMemorySaver(serde=checkpoint_serde())
        yield _memory_saver
        return
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with AsyncPostgresSaver.from_conn_string(postgres_conn_string(database_url), serde=checkpoint_serde()) as saver:
        yield saver


CHECKPOINT_SETUP_LOCK = 7_262_016  # pg advisory lock: several API processes start at once


async def _try_lock(conn: Any) -> bool:
    row = await (await conn.execute("SELECT pg_try_advisory_lock(%s) AS locked", (CHECKPOINT_SETUP_LOCK,))).fetchone()
    return bool(row["locked"] if isinstance(row, dict) else row[0])


async def setup_checkpointer(database_url: str) -> None:
    async with open_checkpointer(database_url) as saver:
        if not hasattr(saver, "setup"):
            return
        conn = getattr(saver, "conn", None)
        if conn is None or database_url.startswith("sqlite"):
            await saver.setup()
            return
        # Non-blocking attempts: LangGraph's migrations use CREATE INDEX CONCURRENTLY, which waits for every open
        # transaction, including a session blocked in pg_advisory_lock (deadlock).
        while not await _try_lock(conn):  # noqa: ASYNC110 — polling a database lock, not an in-process event
            await asyncio.sleep(0.5)
        try:
            await saver.setup()
        finally:
            await conn.execute("SELECT pg_advisory_unlock(%s)", (CHECKPOINT_SETUP_LOCK,))


@dataclass
class RunOutcome:
    state: NovaState
    waiting_for: dict[str, Any] | None  # interrupt payload when the execution waits for the user


class AgentRuntime:
    def __init__(self, checkpointer: Any) -> None:
        self.graph = build_graph(checkpointer)

    async def run(
        self,
        task_id: str,
        deps: AgentDeps,
        *,
        initial: NovaState | None = None,
        resume: Any = None,
        retry: bool = False,
        parent: otel_context.Context | None = None,
    ) -> RunOutcome:
        config = {"configurable": {"thread_id": task_id}, "recursion_limit": RECURSION_LIMIT}
        with tracer.start_as_current_span("invoke_agent nova", context=parent) as span:
            span.set_attribute("gen_ai.operation.name", "invoke_agent")
            span.set_attribute("gen_ai.agent.name", "nova")
            span.set_attribute("gen_ai.request.model", deps.llm.model_name)
            span.set_attribute("nova.task_id", task_id)
            span.set_attribute("nova.version", deps.settings.version)
            trace_id = format(span.get_span_context().trace_id, "032x")
            if initial is not None:
                span.set_attribute("nova.intent", redact(initial.intent[:500]))
                payload: Any = initial.model_copy(update={"trace_id": initial.trace_id or trace_id})
            elif resume is not None:
                payload = Command(resume=resume)
            elif retry:
                payload = None
                config = await self._retry_config(config)
            else:
                raise ValueError("initial, resume or retry is required")
            await self.graph.ainvoke(payload, config, context=deps)
            snapshot = await self.graph.aget_state({"configurable": {"thread_id": task_id}})
        state = NovaState.model_validate(snapshot.values)
        interrupts = [i for task in snapshot.tasks for i in (task.interrupts or ())]
        return RunOutcome(state=state, waiting_for=interrupts[0].value if interrupts else None)

    async def has_checkpoint(self, task_id: str) -> bool:
        snapshot = await self.graph.aget_state({"configurable": {"thread_id": task_id}})
        return bool(snapshot and snapshot.values)

    async def _retry_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Resume point for a retry: the interrupted node if the run crashed, otherwise the last checkpoint
        that was still running before the execution was marked failed (completed steps are kept)."""
        snapshot = await self.graph.aget_state(config)
        if snapshot.next and snapshot.values.get("status") == "running":
            return config
        async for past in self.graph.aget_state_history(config):
            if past.next and past.values.get("status") == "running" and "finalize" not in past.next:
                return {**past.config, "recursion_limit": RECURSION_LIMIT}
        return config

    async def current_state(self, task_id: str) -> NovaState | None:
        snapshot = await self.graph.aget_state({"configurable": {"thread_id": task_id}})
        return NovaState.model_validate(snapshot.values) if snapshot and snapshot.values else None
