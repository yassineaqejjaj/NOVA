"""Capture into FORGE respects the classification of the context: above the ceiling no text leaves (synthetic data)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio

from nova.config import get_settings
from nova.domain.evaluation import ExecutionRecord
from nova.infra import db
from nova.infra.models import ProjectReference
from nova.integrations.forge.adapter import ForgeEvaluationSink
from nova.services import providers
from nova.skills.registry import get_skill_registry
from nova_api.main import create_app
from tests.support.fakes import context_item

from .test_api import _ask, _client, _project

SECRET_TEXT = "SYNTHETIC-C3-EXCERPT-DO-NOT-LEAK"
INTENT = "Draft the SYNTHETIC-INTENT roadmap, contact jane.doe@example.com"


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


class SpyClient:
    """FORGE as seen from NOVA: records everything that would be sent."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def _log(self, name: str, body: dict) -> None:
        self.calls.append((name, body))

    async def find_agent(self, slug):
        return {"id": "agent-1"}

    async def list_agent_versions(self, agent_id):
        return []

    async def create_agent_version(self, agent_id, body):
        self._log("version", body)
        return {"id": "av-1", **body}

    async def create_scenario(self, body):
        self._log("scenario", body)
        return {"id": "sc-1"}

    async def find_scenario(self, slug):
        return None

    async def find_evaluation_config(self, key):
        return {"id": "cfg-1"}

    async def create_runs(self, body):
        self._log("runs", body)
        return [{"id": "run-1", "status": "pending"}]

    async def create_observed_run(self, body):
        self._log("observed", body)
        return {"id": "run-1", "status": "evaluating"}

    def sent(self) -> str:
        return json.dumps(self.calls, default=str)

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]


@pytest.fixture(autouse=True)
def forge_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "forge_api_key", "fgk_test")
    monkeypatch.setattr(settings, "forge_nova_endpoint", "https://nova-api.example")
    monkeypatch.setattr(settings, "forge_credential_id", "configured-credential")
    monkeypatch.setattr(settings, "forge_capture_policy", "all")


def sink(spy: SpyClient) -> ForgeEvaluationSink:
    return ForgeEvaluationSink(get_settings(), get_skill_registry(), "m", client=spy)  # type: ignore[arg-type]


def record(level: int, *, doc_level: int | None = None, **over) -> ExecutionRecord:
    now = datetime.now(UTC)
    doc = {"id": "S1", "title": "Synthetic plan", "content": SECRET_TEXT, "source": "orbit", "classification": doc_level or level}
    base = dict(
        task_id=str(uuid.uuid4()), trace_id=None, user_intent=INTENT, origin="interactive", agent_version="0.1.0", model="m",
        status="completed", started_at=now, finished_at=now, context_documents=[doc], context_max_classification=level,
    )  # fmt: skip
    return ExecutionRecord(**{**base, **over})


async def test_a_secret_run_is_not_captured_by_reexecution_and_says_so(monkeypatch):
    spy = SpyClient()
    reference = await sink(spy).capture(record(3))
    assert reference is not None and reference.status == "skipped" and reference.run_id is None
    assert "C3" in (reference.note or "") and "C1" in (reference.note or "")
    assert spy.calls == []  # not even the agent version: nothing at all went to FORGE


async def test_one_classified_document_is_enough_even_when_the_maximum_says_otherwise():
    spy = SpyClient()
    reference = await sink(spy).capture(record(0, doc_level=2))
    assert reference.status == "skipped" and spy.calls == []


async def test_a_document_without_classification_is_read_as_secret():
    spy = SpyClient()
    legacy = record(0, context_documents=[{"id": "S1", "title": "t", "content": SECRET_TEXT, "source": "orbit"}])
    assert (await sink(spy).capture(legacy)).status == "skipped" and spy.calls == []


async def test_an_internal_run_is_captured_with_its_request_redacted_of_personal_data():
    spy = SpyClient()
    reference = await sink(spy).capture(record(1))
    assert reference.status == "pending" and spy.names() == ["version", "scenario", "runs"]
    scenario = dict(spy.calls)["scenario"]
    assert "jane.doe@example.com" not in spy.sent() and "[EMAIL]" in scenario["content"]["input"]["prompt"]
    assert "SYNTHETIC-INTENT" in scenario["content"]["input"]["prompt"]  # the request itself still travels at C1
    assert scenario["content"]["context"]["documents"][0]["classification"] == 1


async def test_the_ceiling_is_configurable(monkeypatch):
    monkeypatch.setattr(get_settings(), "forge_max_capture_classification", 3)
    spy = SpyClient()
    assert (await sink(spy).capture(record(3))).status == "pending" and "scenario" in spy.names()


async def test_observed_capture_of_a_secret_run_sends_metadata_but_no_text_even_with_intent_enabled(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "forge_capture_mode", "observed")
    monkeypatch.setattr(settings, "forge_capture_intent", True)
    spy = SpyClient()
    s = sink(spy)

    async def ids():
        return "sc-1", "cfg-1"

    monkeypatch.setattr(s, "_production_ids", ids)
    reference = await s.capture(record(3))
    assert reference.run_id == "run-1"
    body = dict(spy.calls)["observed"]
    assert body["output_json"]["context_max_classification"] == 3
    assert "SYNTHETIC-INTENT" not in spy.sent() and SECRET_TEXT not in spy.sent() and "jane.doe" not in spy.sent()
    internal = sink(SpyClient())
    monkeypatch.setattr(internal, "_production_ids", ids)
    await internal.capture(record(1))
    assert "SYNTHETIC-INTENT" in json.dumps(internal.client.calls, default=str)  # allowed below the ceiling (opt-in)


async def test_a_refreshed_skipped_reference_stays_as_it_is():
    spy = SpyClient()
    reference = await sink(spy).capture(record(3))
    assert await sink(spy).refresh(reference) == reference


async def test_a_secret_run_shows_why_it_was_not_captured_and_nothing_reaches_forge(app, orbit, monkeypatch):
    spy = SpyClient()
    providers.override("evaluation", sink(spy))
    orbit.items = [context_item(1, "Synthetic plan", classification=3, excerpt=SECRET_TEXT)]
    client = await _client(app)
    project_id = await _project(client)
    async with db.session_scope() as session:
        session.add(ProjectReference(project_id=uuid.UUID(project_id), system="orbit", external_id="forge", label="FORGE"))
    result = await _ask(client, "Create a PRD for scheduled CSV exports", project_id=project_id)
    task = (await client.get(f"/api/v1/tasks/{result['task_id']}")).json()
    assert task["evaluation"]["status"] == "skipped" and "C3" in task["evaluation"]["note"]
    assert spy.calls == []


async def test_unhelpful_feedback_on_a_secret_run_is_not_captured_and_reports_it(app, orbit, monkeypatch):
    monkeypatch.setattr(get_settings(), "forge_capture_policy", "on_feedback")
    spy = SpyClient()
    providers.override("evaluation", sink(spy))
    orbit.items = [context_item(1, "Synthetic plan", classification=3, excerpt=SECRET_TEXT)]
    client = await _client(app)
    project_id = await _project(client)
    async with db.session_scope() as session:
        session.add(ProjectReference(project_id=uuid.UUID(project_id), system="orbit", external_id="forge", label="FORGE"))
    result = await _ask(client, "Create a PRD for scheduled CSV exports", project_id=project_id)
    response = await client.post(
        "/api/v1/feedback", json={"rating": "not_useful", "comment": "Vague", "message_id": result["reply"]["id"]}
    )
    assert response.status_code == 201 and response.json()["forwarded"]["forge"] == "skipped"
    assert spy.calls == []  # no scenario, no run, no comment
    task = (await client.get(f"/api/v1/tasks/{result['task_id']}")).json()
    assert task["evaluation"]["status"] == "skipped"
