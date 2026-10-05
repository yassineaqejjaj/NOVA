"""LangGraph execution end to end (SQLite + scripted LLM + fake ORBIT/FORGE)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from nova.domain.outputs import IntentClassification, PlanOutput
from nova.infra import db
from nova.infra.models import Artifact, ArtifactVersion, ContextRetrievalReference, Message, Task, TaskStep
from nova.services.conversations import ComposerInput, create_conversation, submit
from nova.services.executions import run_task
from nova.skills.registry import get_skill_registry


async def _start(user, project_id: str | None, text: str, **composer) -> tuple[str, str]:
    async with db.session_scope() as session:
        conversation = await create_conversation(session, user, project_id=project_id, title=None)
        _, reply, task = await submit(
            session,
            user,
            conversation,
            ComposerInput(text=text, project_id=project_id, **composer),
            {s.id for s in get_skill_registry().all()},
        )
        return str(task.id), str(reply.id)


async def _task(task_id: str) -> Task:
    async with db.session_scope() as session:
        return await session.get(Task, uuid.UUID(task_id))


async def _blocks(message_id: str) -> dict[str, dict]:
    async with db.session_scope() as session:
        message = await session.get(Message, uuid.UUID(message_id))
        return {b.key: {"type": b.type, **b.payload} for b in message.blocks}


async def test_prd_single_skill_creates_structured_artifact_with_validated_citations(user, project, llm, orbit, forge):
    task_id, message_id = await _start(user, project, "Create a PRD for scheduled CSV exports in FORGE")
    status = await run_task(task_id, "start")
    assert status == "completed"

    task = await _task(task_id)
    assert task.progress_done == task.progress_total == 1
    assert task.trace_id and len(task.trace_id) == 32

    async with db.session_scope() as session:
        artifact = await session.scalar(select(Artifact).where(Artifact.task_id == uuid.UUID(task_id)))
        assert artifact is not None and artifact.type == "prd" and artifact.current_version == 1
        version = await session.scalar(select(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact.id))
        content = version.content
        reqs = content["sections"]["functional_requirements"]["items"]
        assert reqs and all(r["kind"] == "requirement" for r in reqs)
        labels = {c["label"] for r in reqs for c in r["citations"]}
        assert labels == {"S1"}  # S99 was not served by ORBIT → dropped
        ref = await session.scalar(
            select(ContextRetrievalReference).where(ContextRetrievalReference.task_id == uuid.UUID(task_id))
        )
        assert reqs[0]["citations"][0]["ref"] == str(ref.id)
        assert ref.retrieval_id == "orbit-req-1"

    blocks = await _blocks(message_id)
    assert blocks["context"]["type"] == "context_sources" and len(blocks["context"]["items"]) == 2
    step = blocks["plan"]["steps"][0]
    assert step["status"] == "completed" and step["agent"] == "product"  # carried out by the PRD's sub-agent
    assert step["started_at"] <= step["finished_at"]
    assert any(k.startswith("artifact-") for k in blocks)
    assert blocks["text"]["markdown"].startswith("Created")
    progress = {line["key"]: line for line in blocks["progress"]["lines"]}
    assert progress["context"]["status"] == "completed" and all(v["status"] == "completed" for v in progress.values())
    # NOVA's Validation agent verified the deliverable before it was saved
    assert progress["1-write-the-prd:validate"]["detail"].startswith("Approved")
    assert step["validation"]["status"] == "passed" and step["validation"]["reviewed"]
    assert all(c["passed"] for c in step["validation"]["checks"])
    assert orbit.queries[0].project_slug == "forge"
    assert forge.captured == []  # capture policy on_feedback


async def test_multi_skill_workflow_requires_confirmation_in_assist_mode(user, project, llm):
    llm.plan = lambda m: PlanOutput(
        objective="Idea to build",
        steps=[
            {"id": "a", "title": "Write the PRD", "skill_id": "prd"},
            {"id": "b", "title": "Backlog", "skill_id": "vision-to-backlog"},
        ],
    )
    llm.intent = lambda m: IntentClassification(
        kind="run_workflow", goal="Idea to backlog", candidate_skill_ids=["prd", "vision-to-backlog"]
    )
    task_id, message_id = await _start(user, project, "Turn my product idea into a PRD and a backlog engineering can build")
    assert await run_task(task_id, "start") == "waiting_user"
    task = await _task(task_id)
    assert task.waiting_for["kind"] == "confirm_workflow"
    blocks = await _blocks(message_id)
    assert blocks["workflow"]["status"] == "proposed" and len(blocks["workflow"]["steps"]) == 2

    # The user edits the workflow: keeps only the PRD.
    assert await run_task(task_id, "resume", {"action": "run", "skill_ids": ["prd"]}) == "completed"
    task = await _task(task_id)
    assert task.progress_total == 1 and task.progress_done == 1


async def test_missing_required_input_asks_one_question_then_resumes(user, project, llm):
    llm.plan = lambda m: PlanOutput(
        objective="PRD",
        steps=[{"id": "a", "title": "PRD", "skill_id": "prd"}],
        missing_inputs=[
            {"key": "idea", "question": "What is the idea?", "skill_id": "prd"},
            {"key": "budget", "question": "Budget?", "skill_id": "prd"},
        ],
    )
    task_id, message_id = await _start(user, project, "Create a PRD for this idea")
    assert await run_task(task_id, "start") == "waiting_user"
    blocks = await _blocks(message_id)
    assert [q["key"] for q in blocks["questions"]["questions"]] == ["idea"]  # undeclared "budget" is not asked

    llm.plan = lambda m: PlanOutput(objective="PRD", steps=[{"id": "a", "title": "PRD", "skill_id": "prd"}])
    assert await run_task(task_id, "resume", {"idea": "Scheduled CSV exports"}) == "completed"
    step_prompts = [m for name, m in llm.calls if name == "RawStepOutput"]
    assert "Scheduled CSV exports" in step_prompts[0][1].content


async def test_orbit_permission_error_is_explained_and_execution_continues(user, project, orbit, llm):
    from nova.domain.context import ContextError

    llm.plan = lambda m: PlanOutput(
        objective="Sprint 19", steps=[{"id": "a", "title": "Plan the sprint", "skill_id": "sprint-planning"}]
    )
    orbit.error = ContextError("forbidden", "Accès réservé aux membres du projet")
    task_id, message_id = await _start(user, project, "Prepare Sprint 19")
    assert await run_task(task_id, "start") == "completed"
    warning = (await _blocks(message_id))["context_warning"]
    assert warning["title"] == "NOVA couldn't access this project's context"
    assert [a["action"] for a in warning["actions"]] == ["request_access", "choose_source", "retry"]


async def test_retryable_llm_failure_is_retried_by_the_graph(user, project, llm):
    llm.fail_times = 2  # LangGraph RetryPolicy (3 attempts) absorbs it
    task_id, _ = await _start(user, project, "Create a PRD for audit logs")
    assert await run_task(task_id, "start") == "completed"


async def test_requested_deliverable_skill_is_always_planned(user, project, llm):
    """The model planned smaller Skills only; NOVA adds the PRD Skill the user asked for (live finding)."""
    llm.plan = lambda m: PlanOutput(
        objective="PRD", steps=[{"id": "a", "title": "User stories", "skill_id": "user-story-generation"}]
    )
    task_id, message_id = await _start(user, project, "Create a PRD for QR-code desk check-in")
    assert await run_task(task_id, "start") == "waiting_user"  # 2 steps → workflow confirmation (assist)
    blocks = await _blocks(message_id)
    assert blocks["workflow"]["steps"][0]["skill_id"] == "prd"
    assert "plan" not in blocks  # the plan block appears only once the workflow is confirmed


async def test_pause_stops_at_a_step_boundary_and_continue_resumes_from_the_checkpoint(user, project, llm, orbit, monkeypatch):
    from nova.services.execution_store import SqlExecutionStore as ExecutionStore

    task_id, _ = await _start(user, project, "Create a PRD for scheduled CSV exports in FORGE")
    calls = {"n": 0}
    original = ExecutionStore.is_paused

    async def paused_after_two_nodes(self, tid):  # the user presses Pause while NOVA works
        calls["n"] += 1
        return calls["n"] >= 3

    monkeypatch.setattr(ExecutionStore, "is_paused", paused_after_two_nodes)
    assert await run_task(task_id, "start") == "paused"
    task = await _task(task_id)
    assert task.status == "paused" and task.finished_at is None

    monkeypatch.setattr(ExecutionStore, "is_paused", original)
    async with db.session_scope() as session:
        (await session.get(Task, uuid.UUID(task_id))).status = "queued"  # what POST /continue does
    assert await run_task(task_id, "retry") == "completed"
    async with db.session_scope() as session:
        artifacts = (await session.scalars(select(Artifact).where(Artifact.task_id == uuid.UUID(task_id)))).all()
    assert len(artifacts) == 1  # resumed, not restarted: one PRD


async def test_nova_core_decomposes_assigns_validates_and_hands_off_between_sub_agents(user, project, llm):
    """NOVA (orchestrator) decomposes the task, assigns each step to the sub-agent owning its Skill, has the
    Validation agent verify each deliverable (one revision when needed) and passes a handoff to the next agent."""
    llm.intent = lambda m: IntentClassification(
        kind="run_workflow", goal="Design then build onboarding", candidate_skill_ids=["design-brief", "technical-design"]
    )
    llm.plan = lambda m: PlanOutput(
        objective="Design then build onboarding",
        steps=[
            {"id": "a", "title": "Brief", "skill_id": "design-brief", "goal": "Frame the onboarding problem for designers"},
            {"id": "b", "title": "Tech design", "skill_id": "technical-design", "goal": "Design the onboarding service"},
        ],
    )
    reviews = iter(
        [
            {"verdict": "revise", "issues": [{"section": "problem", "problem": "Too vague", "fix": "Name the users"}]},
            {"verdict": "pass", "summary": "Sound design."},
        ]
    )
    llm.review = lambda m: next(reviews)
    task_id, message_id = await _start(
        user, project, "Design the onboarding and its technical design", autonomy="execute_automatically"
    )
    assert await run_task(task_id, "start") == "completed"

    plan = (await _blocks(message_id))["plan"]
    brief, tech = plan["steps"]
    assert (brief["agent"], tech["agent"]) == ("design", "engineering")  # assignment & routing
    assert brief["goal"] == "Frame the onboarding problem for designers"  # decomposition
    assert brief["validation"]["status"] == "revised" and brief["validation"]["revisions"] == 1
    assert tech["validation"]["status"] == "passed"
    assert brief["handoff"]["from"] == "design" and brief["handoff"]["to"] == "engineering"

    names = [name for name, _ in llm.calls]
    assert names.count("ValidationReview") == 2
    revision = next(m for name, m in llm.calls if name == "RawStepOutput" and "REVISION REQUESTED" in m[1].content)
    assert "SUB-AGENT: you are NOVA's Design agent" in revision[0].content  # the specialist revises its own work
    assert "problem: Too vague → Name the users" in revision[1].content
    tech_steps = [m for name, m in llm.calls if name == "RawStepOutput" and "you are NOVA's Engineering agent" in m[0].content]
    assert "YOUR ASSIGNMENT FROM NOVA" in tech_steps[0][1].content
    assert "delivered by NOVA's Design agent" in tech_steps[0][1].content  # inter-agent communication
    review = next(m for name, m in llm.calls if name == "ValidationReview")
    assert "NOVA's Validation agent" in review[0].content

    async with db.session_scope() as session:
        rows = (await session.scalars(select(TaskStep).where(TaskStep.task_id == uuid.UUID(task_id)))).all()
        report = {r.step_key: r.report for r in rows}
    assert report["1-brief"]["validation"]["status"] == "revised" and report["1-brief"]["handoff"]["to"] == "engineering"


async def test_explicit_skill_asks_its_question_in_the_users_language(user, project, llm):
    llm.intent = lambda m: IntentClassification(kind="run_workflow", goal="Un epic", response_language="fr")
    task_id, message_id = await _start(user, project, "/epic-definition")
    assert await run_task(task_id, "start") == "waiting_user"
    question = (await _blocks(message_id))["questions"]["questions"][0]["question"]
    assert question == get_skill_registry().get("epic-definition").translations["fr"]["inputs"]["epic"]["question"]
