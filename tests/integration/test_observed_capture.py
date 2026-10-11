"""Observed capture: failures are reported too, with the real start time and the run manifest."""

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


async def test_a_failed_run_is_captured_in_observed_mode_with_start_time_and_manifest(app, llm, forge, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "forge_capture_policy", "all")
    monkeypatch.setattr(settings, "forge_capture_mode", "observed")
    client = await _client(app)
    await client.patch("/api/v1/me/preferences", json={"action_permissions": {"artifacts.create": "never"}})
    result = await _ask(client, "Create a PRD for SSO")
    task = (await client.get(f"/api/v1/tasks/{result['task_id']}")).json()
    assert task["status"] == "failed"

    (record,) = [r for r in forge.captured if r.task_id == result["task_id"]]
    assert record.status == "failed" and record.errors
    assert record.started_at is not None and record.finished_at >= record.started_at
    assert record.manifest["run_id"] == result["task_id"] and record.manifest["agent_version"]


async def test_failures_stay_uncaptured_in_the_default_reexecution_mode(app, llm, forge, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "forge_capture_policy", "all")
    client = await _client(app)
    await client.patch("/api/v1/me/preferences", json={"action_permissions": {"artifacts.create": "never"}})
    result = await _ask(client, "Create a PRD for SSO")
    assert not [r for r in forge.captured if r.task_id == result["task_id"]]


class FakeClient:
    def __init__(self) -> None:
        self.scenarios, self.configs, self.observed = [], [], []

    async def find_scenario(self, slug):
        return None

    async def create_scenario(self, body):
        self.scenarios.append(body)
        return {"id": "sc-1"}

    async def find_evaluation_config(self, key):
        return None

    async def create_evaluation_config(self, body):
        self.configs.append(body)
        return {"id": "cfg-1"}

    async def create_observed_run(self, body):
        self.observed.append(body)
        return {"id": f"run-{len(self.observed)}", "status": "evaluating"}


async def test_the_observed_scenario_and_config_are_created_once_and_runs_are_idempotent(monkeypatch):
    from datetime import UTC, datetime

    from sqlalchemy import delete

    from nova.domain.evaluation import ExecutionRecord
    from nova.infra import db
    from nova.infra.models import IntegrationReference

    async with db.session_scope() as session:  # the test database is shared: start without cached FORGE ids
        await session.execute(delete(IntegrationReference).where(IntegrationReference.nova_type == "production"))
    settings = get_settings()
    monkeypatch.setattr(settings, "forge_api_key", "fgk_test")
    monkeypatch.setattr(settings, "forge_capture_mode", "observed")
    client = FakeClient()
    sink = ForgeEvaluationSink(settings, get_skill_registry(), "m", client=client)  # type: ignore[arg-type]

    async def version_id():
        return "av-1"

    monkeypatch.setattr(sink, "agent_version_id", version_id)
    now = datetime.now(UTC)

    def rec(task_id: str) -> ExecutionRecord:
        return ExecutionRecord(
            task_id=task_id, trace_id=None, user_intent="x", origin="interactive", agent_version="0.1.0", model="m",
            status="completed", started_at=now, finished_at=now,
        )  # fmt: skip

    first = await sink.capture(rec("t-1"))
    second = await sink.capture(rec("t-2"))
    assert first.run_id == "run-1" and second.run_id == "run-2" and first.scenario_id == "sc-1"
    assert len(client.scenarios) == 1 and len(client.configs) == 1  # cached after the first capture
    assert [b["external_id"] for b in client.observed] == ["nova-task:t-1", "nova-task:t-2"]
    assert all(
        b["scenario_id"] == "sc-1" and b["evaluation_config_id"] == "cfg-1" and b["agent_version_id"] == "av-1"
        for b in client.observed
    )
