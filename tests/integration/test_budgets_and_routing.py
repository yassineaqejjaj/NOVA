"""Spending limits stop a run cleanly; Skills can be written by a routed model (organization models only)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from nova.config import get_settings
from nova.infra import db
from nova.infra.models import LLMCall, Task
from nova.services import providers
from nova.services.conversations import ComposerInput, create_conversation, submit
from nova.services.executions import run_task
from nova.skills.registry import get_skill_registry


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


async def test_a_token_budget_stops_the_run_before_the_next_call_and_keeps_what_was_done(
    user, project, llm, orbit, forge, monkeypatch
):
    monkeypatch.setattr(get_settings(), "run_token_budget", 1)  # reached by the very first call
    task_id = await _ask(user, project)
    assert await run_task(task_id, "start") == "failed"
    async with db.session_scope() as session:
        task = await session.get(Task, uuid.UUID(task_id))
        calls = (await session.scalars(select(LLMCall).where(LLMCall.task_id == task.id))).all()
    assert "limit of 1 tokens" in task.error
    assert len(calls) == 1 and calls[0].status == "ok"  # one call went through, the second was refused


async def test_a_cost_budget_needs_prices_and_a_user_budget_is_per_day(user, project, llm, orbit, forge, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_price_input_per_mtok", 1_000_000.0)  # every token costs $1
    monkeypatch.setattr(settings, "run_cost_budget_usd", 5.0)
    task_id = await _ask(user, project)
    assert await run_task(task_id, "start") == "failed"
    async with db.session_scope() as session:
        assert "cost limit ($5)" in (await session.get(Task, uuid.UUID(task_id))).error

    monkeypatch.setattr(settings, "run_cost_budget_usd", 0.0)
    monkeypatch.setattr(settings, "user_daily_cost_budget_usd", 1.0)  # the previous run already cost far more today
    second = await _ask(user, project)
    assert await run_task(second, "start") == "failed"
    async with db.session_scope() as session:
        assert "today's usage limit" in (await session.get(Task, uuid.UUID(second))).error


async def test_no_limit_configured_means_no_check(user, project, llm, orbit, forge):
    assert await run_task(await _ask(user, project), "start") == "completed"


class Named:
    def __init__(self, inner, name: str) -> None:
        self._inner, self.model_name, self.used = inner, name, 0

    async def structured_output(self, *a, **k):
        self.used += 1
        return await self._inner.structured_output(*a, **k)

    async def generate(self, *a, **k):
        return await self._inner.generate(*a, **k)

    def stream(self, *a, **k):
        return self._inner.stream(*a, **k)


async def test_a_skill_can_be_written_by_a_routed_organization_model_but_never_an_arbitrary_one(
    user, project, llm, orbit, forge, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "replay_models", ["cheap-model"])
    monkeypatch.setattr(settings, "llm_skill_models", {"prd": "cheap-model", "vision-to-backlog": "rogue-model"})
    routed: dict[str, Named] = {}

    def build(s):
        routed[s.llm_model] = Named(llm, s.llm_model)
        return routed[s.llm_model]

    monkeypatch.setattr("nova.services.executions.build_llm_provider", build)
    providers.override("llm", Named(llm, "main-model"))
    assert await run_task(await _ask(user, project), "start") == "completed"
    assert set(routed) == {"cheap-model"}  # "rogue-model" is not an allowed model: never even built
    assert routed["cheap-model"].used >= 1  # the PRD's generation steps went to the routed model
