"""A run survives an outage of the main model by falling back, and every attempt is recorded."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from nova.agent.providers import fallback
from nova.config import get_settings
from nova.domain.llm import LLMError
from nova.infra import db
from nova.infra.models import LLMCall, Task
from nova.services import providers
from nova.services.conversations import ComposerInput, create_conversation, submit
from nova.services.executions import run_task
from nova.skills.registry import get_skill_registry


class Named:
    """A provider under another model name (so each has its own circuit breaker)."""

    def __init__(self, inner, name: str, fail: bool = False) -> None:
        self._inner, self.model_name, self.fail = inner, name, fail

    async def generate(self, *a, **k):
        if self.fail:
            raise LLMError("inference server overloaded", retryable=True)
        return await self._inner.generate(*a, **k)

    async def structured_output(self, *a, **k):
        if self.fail:
            raise LLMError("inference server overloaded", retryable=True)
        return await self._inner.structured_output(*a, **k)

    def stream(self, *a, **k):
        if self.fail:
            raise LLMError("inference server overloaded", retryable=True)
        return self._inner.stream(*a, **k)


async def _ask(user, project) -> str:
    async with db.session_scope() as session:
        conversation = await create_conversation(session, user, project_id=project, title=None)
        _, _, task = await submit(
            session,
            user,
            conversation,
            ComposerInput(text="Create a PRD for scheduled CSV exports in FORGE", project_id=project),
            {s.id for s in get_skill_registry().all()},
        )
        return str(task.id)


async def test_a_run_completes_on_the_backup_model_and_records_each_attempt(user, project, llm, orbit, forge, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_fallback_models", ["backup-model"])
    fallback._BREAKERS.clear()
    providers.override("llm", Named(llm, "main-model", fail=True))
    monkeypatch.setattr("nova.services.executions.build_llm_provider", lambda s: Named(llm, s.llm_model))

    task_id = await _ask(user, project)
    assert await run_task(task_id, "start") == "completed"

    async with db.session_scope() as session:
        rows = (
            (await session.execute(select(LLMCall).where(LLMCall.task_id == uuid.UUID(task_id)).order_by(LLMCall.seq)))
            .scalars()
            .all()
        )
        task = await session.get(Task, uuid.UUID(task_id))
    errors = [r for r in rows if r.status == "error"]
    served = [r for r in rows if r.status == "ok"]
    assert errors and served  # the failed attempts and the successful ones are all visible
    assert all(r.error == "LLMError" for r in errors)
    # The circuit opened after 3 failures: later calls skip the main model instead of failing first.
    assert len(errors) == settings.llm_circuit_failures
    assert task.status == "completed" and task.usage["llm_calls"] == len(rows)
    fallback._BREAKERS.clear()
