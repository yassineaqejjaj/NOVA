"""A completed execution carries its run manifest (agent version, context, skills, policies)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from nova.domain.enums import AutonomyMode
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


async def test_the_plan_records_the_team_and_the_manifest_keeps_it(user, project, llm, orbit, forge):
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
        manifest = (await session.get(Task, uuid.UUID(task_id))).run_manifest
    assert manifest["team"] == [{"agent": "product", "skills": ["prd"], "score": None}]


async def _plan_steps(user, project, llm, orbit, verdict, missing):
    orbit.sufficiency, orbit.missing = verdict, missing
    llm.intent = lambda m: IntentClassification(
        kind="run_workflow", goal="PRD", candidate_skill_ids=["prd", "problem-framing"], context_query="scheduled CSV exports"
    )
    async with db.session_scope() as session:
        conversation = await create_conversation(session, user, project_id=project, title=None)
        _, _, task = await submit(
            session,
            user,
            conversation,
            ComposerInput(
                text="Create a PRD for scheduled CSV exports in FORGE",
                project_id=project,
                autonomy=AutonomyMode.execute_automatically,
            ),
            {s.id for s in get_skill_registry().all()},
        )
        task_id = str(task.id)
    assert await run_task(task_id, "start") == "completed"
    async with db.session_scope() as session:
        stored = await session.get(Task, uuid.UUID(task_id))
        from nova.infra.models import TaskStep

        steps = (await session.scalars(select(TaskStep).where(TaskStep.task_id == stored.id).order_by(TaskStep.position))).all()
        return [s.skill_id for s in steps], stored.run_manifest


async def test_an_insufficient_context_puts_a_discovery_step_first(user, project, llm, orbit, forge):
    skills, manifest = await _plan_steps(user, project, llm, orbit, "insufficient", ["refund policy"])
    assert skills[0] == "problem-framing" and "prd" in skills  # gather what is missing, then write the PRD
    assert manifest["context"]["sufficiency"] == "insufficient"
    assert manifest["team"][0]["skills"][0] == "problem-framing"


async def test_a_sufficient_or_partial_context_keeps_the_plan_as_it_is(user, project, llm, orbit, forge):
    for verdict in ("sufficient", "partial", None):
        skills, manifest = await _plan_steps(user, project, llm, orbit, verdict, [])
        assert skills == ["prd"] and manifest["context"]["sufficiency"] == verdict


async def test_compositions_that_worked_for_a_kind_of_request_become_router_bonuses(user):
    from nova.domain.assembly import MAX_COMPOSITION_BONUS
    from nova.services import compositions

    category = f"cat-{uuid.uuid4().hex[:6]}"  # the test database is shared: a category of our own
    manifest = {"category": category, "skills": [{"skill_id": "problem-framing"}, {"skill_id": "prd"}]}
    async with db.session_scope() as session:
        for _ in range(6):
            session.add(
                Task(
                    user_id=uuid.UUID(user.user_id),
                    objective="x",
                    status="completed",
                    origin="interactive",
                    run_manifest=manifest,
                )
            )
        session.add(  # a failed run of another composition, and a replay: neither shapes the prior
            Task(user_id=uuid.UUID(user.user_id), objective="x", status="failed", origin="interactive",
                 run_manifest={"category": category, "skills": [{"skill_id": "persona"}]})
        )  # fmt: skip
        session.add(
            Task(user_id=uuid.UUID(user.user_id), objective="x", status="completed", origin="replay",
                 run_manifest={"category": category, "skills": [{"skill_id": "persona"}]})
        )  # fmt: skip
    compositions.invalidate()
    async with db.session_scope() as session:
        bonuses = await compositions.priors(session, category)
        assert bonuses == {"problem-framing": MAX_COMPOSITION_BONUS, "prd": MAX_COMPOSITION_BONUS}
        assert await compositions.priors(session, "no-such-category") == {}
