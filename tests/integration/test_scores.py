"""A run can be perfectly healthy and still deliver little: the three indicators are reported apart (NOV-83)."""

from __future__ import annotations

import pytest_asyncio

from nova.config import get_settings
from nova.integrations.forge.adapter import ForgeEvaluationSink
from nova.skills.registry import get_skill_registry
from nova_api.main import create_app

from .test_api import _ask, _client


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


async def _scores(client, task_id: str) -> dict:
    return (await client.get(f"/api/v1/tasks/{task_id}")).json()["scores"]


async def test_a_finished_run_with_unverifiable_citations_is_healthy_but_not_top_quality(app, llm):
    client = await _client(app)
    result = await _ask(
        client, "Create a PRD for scheduled CSV exports"
    )  # the scripted model also cites a source that does not exist
    scores = await _scores(client, result["task_id"])
    assert scores["execution_health"] == 100
    checks = {c["key"]: c for c in scores["deliverable_quality"]["checks"]}
    assert checks["has_content"]["value"] == 1 and checks["citations_resolved"]["value"] == 0
    assert 0 < scores["deliverable_quality"]["score"] < 100
    assert scores["business_gain"]["score"] is None  # nobody has judged the deliverable yet: no invented number


async def test_the_rating_and_the_edits_of_people_move_quality_and_business_gain(app, llm):
    client = await _client(app)
    result = await _ask(client, "Create a PRD for scheduled CSV exports")
    before = await _scores(client, result["task_id"])
    await client.post("/api/v1/feedback", json={"rating": "not_useful", "message_id": result["reply"]["id"]})
    after = await _scores(client, result["task_id"])
    assert after["deliverable_quality"]["score"] < before["deliverable_quality"]["score"]
    assert after["execution_health"] == 100  # the run itself did not get any worse
    assert after["business_gain"]["score"] == 0

    again = await _ask(client, "Create a PRD for audit logs")
    await client.post("/api/v1/feedback", json={"rating": "useful", "message_id": again["reply"]["id"]})
    assert (await _scores(client, again["task_id"]))["business_gain"]["score"] == 100


async def test_scores_are_only_given_once_the_run_has_settled(app, llm):
    client = await _client(app)
    result = await _ask(client, "Create a PRD for scheduled CSV exports")
    task = (await client.get(f"/api/v1/tasks/{result['task_id']}")).json()
    assert task["scores"] is not None
    listing = (await client.get("/api/v1/tasks", params={"tab": "completed"})).json()
    assert all("scores" not in t for t in listing)  # the list stays light


async def test_a_capture_says_which_kind_of_score_it_is(monkeypatch):
    from datetime import UTC, datetime

    from nova.domain.evaluation import ExecutionRecord

    settings = get_settings()
    monkeypatch.setattr(settings, "forge_api_key", "fgk_test")
    monkeypatch.setattr(settings, "forge_nova_endpoint", "https://nova-api.example")
    monkeypatch.setattr(settings, "forge_credential_id", "configured-credential")

    class Client:
        async def find_agent(self, slug):
            return {"id": "a"}

        async def list_agent_versions(self, agent_id):
            return []

        async def create_agent_version(self, agent_id, body):
            return {"id": "av", **body}

        async def create_scenario(self, body):
            return {"id": "sc"}

        async def create_runs(self, body):
            return [{"id": "run-1", "status": "pending"}]

        async def find_scenario(self, slug):
            return {"id": "sc"}

        async def find_evaluation_config(self, key):
            return {"id": "cfg"}

        async def create_observed_run(self, body):
            return {"id": "run-2", "status": "evaluating"}

    now = datetime.now(UTC)
    record = ExecutionRecord(
        task_id="t-1", trace_id=None, user_intent="x", origin="interactive", agent_version="0.1.0", model="m",
        status="completed", started_at=now, finished_at=now,
    )  # fmt: skip
    sink = ForgeEvaluationSink(settings, get_skill_registry(), "m", client=Client())  # type: ignore[arg-type]
    assert (await sink.capture(record)).mode == "reexecute"
    monkeypatch.setattr(settings, "forge_capture_mode", "observed")
    assert (await sink.capture(record)).mode == "observed"
