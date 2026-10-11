"""A completed execution carries its run manifest (agent version, context, skills, policies)."""

from __future__ import annotations

import uuid

from nova.domain.outputs import IntentClassification
from nova.infra import db
from nova.infra.models import Task
from nova.services.conversations import ComposerInput, create_conversation, submit
from nova.services.executions import run_task
from nova.skills.registry import get_skill_registry


async def test_completed_run_stores_manifest(user, project, llm, orbit, forge):
    async with db.session_scope() as session:
        conversation = await create_conversation(session, user, project_id=project, title=None)
        _, _, task = await submit(
            session,
            user,
            conversation,
            ComposerInput(text="Create a PRD for scheduled CSV exports in FORGE", project_id=project),
            {s.id for s in get_skill_registry().all()},
        )
        task_id = str(task.id)
    assert await run_task(task_id, "start") == "completed"

    async with db.session_scope() as session:
        stored = await session.get(Task, uuid.UUID(task_id))
        manifest = stored.run_manifest
    assert manifest is not None
    assert manifest["run_id"] == task_id and manifest["trace_id"] == stored.trace_id
    assert manifest["agent_version"] and manifest["origin"] == "interactive"
    assert [s["skill_id"] for s in manifest["skills"]] == ["prd"]
    assert manifest["context"]["retrieval_id"] == "orbit-req-1" and manifest["context"]["items"] == 2
    assert manifest["experiment_id"] is None and manifest["release_id"] is None


async def test_retrieval_adapts_to_the_skill_expected_context(user, project, llm, orbit, forge):
    """The PRD Skill asks for 5000 tokens, the 'specification' purpose and its query hint (skills/prd)."""
    llm.intent = lambda m: IntentClassification(
        kind="run_workflow", goal="PRD", candidate_skill_ids=["prd"], context_query="scheduled CSV exports"
    )
    async with db.session_scope() as session:
        conversation = await create_conversation(session, user, project_id=project, title=None)
        _, _, task = await submit(
            session,
            user,
            conversation,
            ComposerInput(text="Create a PRD for scheduled CSV exports in FORGE", project_id=project),
            {s.id for s in get_skill_registry().all()},
        )
        task_id = str(task.id)
    assert await run_task(task_id, "start") == "completed"
    query = orbit.queries[0]
    assert query.token_budget == 5000 and query.purpose == "specification"
    assert "product vision" in query.task and query.task.startswith("scheduled CSV exports")


async def test_model_calls_are_recorded_and_priced(user, project, llm, orbit, forge, monkeypatch):
    from sqlalchemy import func, select

    from nova.config import get_settings
    from nova.infra.models import LLMCall

    monkeypatch.setattr(get_settings(), "llm_price_input_per_mtok", 1_000_000.0)  # $1 per token, to make the sum visible
    async with db.session_scope() as session:
        conversation = await create_conversation(session, user, project_id=project, title=None)
        _, _, task = await submit(
            session,
            user,
            conversation,
            ComposerInput(text="Create a PRD for scheduled CSV exports in FORGE", project_id=project),
            {s.id for s in get_skill_registry().all()},
        )
        task_id = str(task.id)
    assert await run_task(task_id, "start") == "completed"

    async with db.session_scope() as session:
        stored = await session.get(Task, uuid.UUID(task_id))
        rows = (await session.execute(select(LLMCall).where(LLMCall.task_id == stored.id).order_by(LLMCall.seq))).scalars().all()
        total = await session.scalar(select(func.sum(LLMCall.cost_usd)).where(LLMCall.task_id == stored.id))
    assert rows and [r.seq for r in rows] == list(range(1, len(rows) + 1))
    assert all(r.status == "ok" and r.model for r in rows)
    assert stored.usage["llm_calls"] == len(rows)
    assert stored.usage["cost_usd"] == round(float(total), 6)
    assert stored.usage["cost_usd"] >= 0
