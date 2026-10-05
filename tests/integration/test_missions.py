"""NOVA as a team member: goals planned and carried out as missions, routines, Inbox, Today, presence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest_asyncio

from nova.infra import db
from nova.services import routines as routine_service
from nova_api.main import create_app

from .test_api import _ask, _client, _project


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


async def test_goal_is_planned_carried_out_and_stops_for_the_team_decision(app, llm):
    client = await _client(app)
    project = await _project(client)
    created = await client.post(
        "/api/v1/goals",
        json={
            "title": "Ship Checkout v2",
            "outcome": "Improve checkout conversion",
            "project_id": project,
            "autonomy": "execute_automatically",
            "due_date": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        },
    )
    assert created.status_code == 201, created.text
    goal = created.json()
    assert [m["kind"] for m in goal["milestones"]] == ["skill", "skill", "human"]
    assert goal["milestones"][0]["agent"] == "product"  # routed to the agent owning the Skill

    # NOVA ran both Skill milestones on its own (one after the other), then stopped for the human milestone.
    detail = (await client.get(f"/api/v1/goals/{goal['id']}")).json()
    statuses = [m["status"] for m in detail["milestones"]]
    assert statuses == ["done", "done", "waiting"], statuses
    assert detail["progress"] == {"done": 2, "total": 3, "percent": 67}
    assert detail["mission"] == "waiting"
    assert all(m["artifact_ids"] for m in detail["milestones"][:2])
    prd_task = detail["milestones"][1]["task_id"]
    task = (await client.get(f"/api/v1/tasks/{prd_task}")).json()
    assert task["conversation_id"] == goal["conversation_id"] and task["status"] == "completed"

    inbox = (await client.get("/api/v1/inbox")).json()
    kinds = {i["id"].split(":")[0] + ":" + i["id"].split(":")[1]: i for i in inbox["items"]}
    decision = kinds["goal:human"]
    assert decision["kind"] == "decision" and decision["actions"][0]["action"] == "done"
    validation = next(i for i in inbox["items"] if i["kind"] == "validation")
    assert validation["confidence"]["score"] > 0 and "validation" in validation["confidence"]["evaluated_by"]
    assert inbox["counts"]["decision"] >= 1 and inbox["counts"]["validation"] == 2

    # The user validates a deliverable: it becomes final and leaves the Inbox
    validated = await client.post(f"/api/v1/inbox/validate/{validation['artifact_id']}", json={"inbox_id": validation["id"]})
    assert validated.status_code == 200
    assert (await client.get(f"/api/v1/artifacts/{validation['artifact_id']}")).json()["status"] == "final"
    assert all(i["id"] != validation["id"] for i in (await client.get("/api/v1/inbox")).json()["items"])

    # The team made its decision: the goal is complete
    done = await client.post(
        f"/api/v1/goals/{goal['id']}/actions",
        json={"action": "done", "milestone_id": decision["milestone_id"], "note": "Agreed in the design review"},
    )
    assert done.status_code == 200 and done.json()["status"] == "completed"

    today = (await client.get("/api/v1/today")).json()
    assert today["since"]["count"] >= 2 and today["since"]["worked_on"][0]["origin"] == "goal"
    assert today["pulse"]["sources"] | {"orbit": None} == {
        "orbit": None,
        "forge": False,
        "jira": False,
        "slack": False,
        "analytics": False,
    }

    impact = (await client.get("/api/v1/impact")).json()
    assert impact["tasks"] >= 2 and impact["by_origin"]["goal"] >= 2 and impact["artifacts"] >= 2
    assert impact["hours_saved_estimate"] >= 5 and impact["deliverables_validated"] >= 2 and impact["decisions"] >= 1
    artifact = (await client.get(f"/api/v1/artifacts/{detail['milestones'][1]['artifact_ids'][0]}")).json()
    assert artifact["confidence"]["level"] in ("high", "medium") and "validation" in artifact["confidence"]["evaluated_by"]


async def test_goal_in_suggest_mode_waits_for_the_plan_then_each_step(app, llm):
    client = await _client(app)
    goal = (await client.post("/api/v1/goals", json={"title": "Prepare Q1", "autonomy": "suggest"})).json()
    assert goal["status"] == "proposed" and goal["mission"] == "waiting"
    plan_item = next(i for i in (await client.get("/api/v1/inbox")).json()["items"] if i["id"] == f"goal:plan:{goal['id']}")
    assert plan_item["actions"][0]["action"] == "approve"

    approved = (await client.post(f"/api/v1/goals/{goal['id']}/actions", json={"action": "approve"})).json()
    assert approved["status"] == "active" and approved["milestones"][0]["status"] == "ready"  # NOVA proposes, the user starts
    started = (
        await client.post(
            f"/api/v1/goals/{goal['id']}/actions", json={"action": "start", "milestone_id": approved["milestones"][0]["id"]}
        )
    ).json()
    detail = (await client.get(f"/api/v1/goals/{started['id']}")).json()
    assert [m["status"] for m in detail["milestones"]][:2] == ["done", "ready"]

    observed = (await client.post("/api/v1/goals", json={"title": "Understand churn", "autonomy": "observe"})).json()
    assert observed["status"] == "proposed" and all(m["status"] == "pending" for m in observed["milestones"])


async def test_routine_runs_on_demand_and_on_schedule_and_its_result_reaches_the_inbox(app, llm):
    client = await _client(app)
    templates = (await client.get("/api/v1/routines/templates", headers={"Accept-Language": "fr"})).json()
    weekly = next(t for t in templates if t["id"] == "weekly-brief")
    assert weekly["name"] == "Product Brief hebdomadaire"
    created = await client.post(
        "/api/v1/routines",
        json={
            "name": weekly["name"],
            "instructions": weekly["instructions"],
            "skill_ids": weekly["skill_ids"],
            "schedule": {"kind": "weekly", "days": [0], "time": "08:30"},
            "template": "weekly-brief",
        },
    )
    assert created.status_code == 201, created.text
    routine = created.json()
    next_run = datetime.fromisoformat(routine["next_run_at"])
    assert next_run.astimezone(routine_service.ZoneInfo("Europe/Paris")).strftime("%a %H:%M") == "Mon 08:30"

    ran = (await client.post(f"/api/v1/routines/{routine['id']}/run")).json()
    task = (await client.get(f"/api/v1/tasks/{ran['task_id']}")).json()
    assert task["status"] == "completed" and ran["runs"] == 1
    inbox = (await client.get("/api/v1/inbox")).json()
    assert any(i["kind"] == "result" and i["routine_id"] == routine["id"] for i in inbox["items"])

    # The beat's tick starts routines that are due
    async with db.session_scope() as session:
        due = await routine_service.run_due(session, now=next_run + timedelta(minutes=1))
    assert len(due) == 1
    missions = (await client.get("/api/v1/missions")).json()
    assert missions["routines"][0]["runs"] == 2


async def test_schedules_compute_their_next_run_in_the_user_time_zone():
    monday_evening = datetime(2026, 10, 5, 19, 0, tzinfo=UTC)  # Monday 21:00 in Paris
    assert routine_service.next_run({"kind": "daily", "time": "08:30"}, monday_evening) == datetime(
        2026, 10, 6, 6, 30, tzinfo=UTC
    )
    assert routine_service.next_run({"kind": "weekdays", "time": "08:30"}, datetime(2026, 10, 9, 7, 0, tzinfo=UTC)).weekday() == 0
    assert routine_service.next_run({"kind": "weekly", "days": [4], "time": "17:00"}, monday_evening) == datetime(
        2026, 10, 9, 15, 0, tzinfo=UTC
    )
    assert routine_service.next_run({"kind": "monthly", "day": 1, "time": "09:00"}, monday_evening).day == 1
    assert routine_service.next_run({"kind": "manual"}, monday_evening) is None


async def test_presence_and_today_since_last_visit(app, llm):
    client = await _client(app)
    presence = (await client.get("/api/v1/presence")).json()
    assert presence == {"state": "idle", "running": 0, "waiting": 0, "mission": None}
    assert (await client.post("/api/v1/today/seen")).status_code == 204
    today = (await client.get("/api/v1/today")).json()
    assert today["since"]["count"] == 0 and "recommended" in today and today["inbox"]["counts"]["total"] >= 0


async def test_action_permissions_always_ask_never(app, llm):
    client = await _client(app)
    matrix = (await client.get("/api/v1/me/permissions")).json()
    assert [a["id"] for a in matrix["actions"]] == ["orbit.read", "artifacts.create", "artifacts.update", "orbit.write"]
    assert matrix["actions"][2]["defaults"]["execute_with_approval"] == "ask"
    assert (
        await client.patch("/api/v1/me/preferences", json={"action_permissions": {"jira.delete": "always"}})
    ).status_code == 422

    # Never create: NOVA refuses before producing anything
    await client.patch("/api/v1/me/preferences", json={"action_permissions": {"artifacts.create": "never"}})
    result = await _ask(client, "Create a PRD for SSO")
    task = (await client.get(f"/api/v1/tasks/{result['task_id']}")).json()
    assert task["status"] == "failed" and "not allowed by your permissions" in task["error"]

    # Ask before creating: even a single Skill waits for the user's go
    await client.patch("/api/v1/me/preferences", json={"action_permissions": {"artifacts.create": "ask"}})
    result = await _ask(client, "Create a PRD for SSO")
    task = (await client.get(f"/api/v1/tasks/{result['task_id']}")).json()
    assert task["status"] == "waiting_user" and task["waiting_for"]["kind"] == "confirm_workflow"

    # Never read ORBIT: NOVA works without project context
    await client.patch("/api/v1/me/preferences", json={"action_permissions": {"orbit.read": "never"}})
    result = await _ask(client, "Create a PRD for SSO", project_id=await _project(client))
    progress = next(b for b in result["reply"]["blocks"] if b["type"] == "progress")
    context = next(line for line in progress["data"]["lines"] if line["key"] == "context")
    assert context["status"] == "skipped" and context["detail"] == "Not allowed by your permissions"


async def test_teach_nova_observes_generalises_and_reuses_a_workflow(app, llm):
    client = await _client(app)
    assert (await client.get("/api/v1/teach")).json() == {"active": False, "since": None, "observed": []}
    assert (await client.post("/api/v1/teach/finish", json={})).json()["code"] == "nothing_observed"

    await client.post("/api/v1/teach/start")
    await _ask(client, "Create a PRD for the sprint stories")
    status = (await client.get("/api/v1/teach")).json()
    assert status["active"] and status["observed"][0]["kind"] == "request" and status["observed"][0]["skills"] == ["prd"]

    draft = (
        await client.post("/api/v1/teach/finish", json={"description": "Then I comment each incomplete story in Jira."})
    ).json()
    assert draft["name"] == "Sprint Story Quality Check" and draft["slug"] == "sprint-story-quality-check"
    assert [s["skill_id"] for s in draft["steps"]] == ["backlog-refinement", "acceptance-criteria"]
    assert (await client.get("/api/v1/teach")).json()["active"] is False
    prompt = next(m for name, m in llm.calls if name == "LearnedSkillDraft")[1].content
    assert "Create a PRD for the sprint stories" in prompt and "comment each incomplete story in Jira" in prompt

    saved = (await client.post("/api/v1/learned-skills", json=draft)).json()
    assert saved["slug"] == "sprint-story-quality-check" and len(saved["steps"]) == 2
    assert [s["slug"] for s in (await client.get("/api/v1/learned-skills")).json()] == ["sprint-story-quality-check"]

    # "/sprint-story-quality-check" in the composer runs the learned workflow with its Skills
    ran = await _ask(client, "/sprint-story-quality-check for Sprint 21", autonomy="execute_automatically")
    task = (await client.get(f"/api/v1/tasks/{ran['task_id']}")).json()
    assert [s["skill_id"] for s in task["steps"]] == ["backlog-refinement", "acceptance-criteria"]
    step_prompt = next(m for name, m in llm.calls[::-1] if name == "RawStepOutput")[1].content
    assert "Follow this learned workflow" in step_prompt and "for Sprint 21" in step_prompt
    again = (await client.post(f"/api/v1/learned-skills/{saved['id']}/run", json={})).json()
    assert again["task_id"]
    assert (await client.get("/api/v1/learned-skills")).json()[0]["uses"] == 2
