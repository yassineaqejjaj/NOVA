"""FORGE capture outbox: a run finished while FORGE was down is captured once FORGE is back, exactly once (synthetic data)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from nova.config import get_settings
from nova.domain.evaluation import ExecutionRecord
from nova.infra import db
from nova.infra.models import ForgeOutbox, IntegrationReference, ProjectReference, User
from nova.integrations.forge.adapter import ForgeEvaluationSink
from nova.integrations.forge.client import ForgeError
from nova.services import forge_outbox, maintenance, providers
from nova.skills.registry import get_skill_registry
from nova_api.main import create_app

from .test_api import _ask, _client, _project


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


class Forge:
    """FORGE as the capture sees it, up or down; observed runs are idempotent on ``external_id`` like the real thing."""

    def __init__(self) -> None:
        self.error: Exception | None = ForgeError(0, "FORGE unreachable (ConnectError)")
        self.attempts = 0
        self.observed: dict[str, dict] = {}

    def check(self) -> None:
        self.attempts += 1
        if self.error:
            raise self.error

    async def find_scenario(self, slug):
        self.check()
        return {"id": "sc-1"}

    async def find_evaluation_config(self, key):
        return {"id": "cfg-1"}

    async def find_agent(self, slug):
        return {"id": "agent-1"}

    async def list_agent_versions(self, agent_id):
        return []

    async def create_agent_version(self, agent_id, body):
        return {"id": "av-1", **body}

    async def create_scenario(self, body):
        self.check()
        return {"id": "sc-1"}

    async def create_runs(self, body):
        return [{"id": "run-1", "status": "pending"}]

    async def create_observed_run(self, body):
        self.check()
        self.observed.setdefault(body["external_id"], body)
        return {"id": f"run-{len(self.observed)}", "status": "evaluating"}


@pytest.fixture
def forge(monkeypatch) -> Forge:
    settings = get_settings()
    monkeypatch.setattr(settings, "forge_api_key", "fgk_test")
    monkeypatch.setattr(settings, "forge_capture_policy", "all")
    monkeypatch.setattr(settings, "forge_capture_mode", "observed")
    fake = Forge()
    sink = ForgeEvaluationSink(settings, get_skill_registry(), "m", client=fake)  # type: ignore[arg-type]
    providers.override("evaluation", sink)
    return fake


@pytest_asyncio.fixture(autouse=True)
async def clean():
    async def wipe() -> None:
        async with db.session_scope() as session:
            await session.execute(delete(ForgeOutbox))
            await session.execute(
                delete(IntegrationReference).where(IntegrationReference.kind.in_(("scenario", "evaluation_config")))
            )

    await wipe()
    yield
    await wipe()


async def rows() -> list[ForgeOutbox]:
    async with db.session_scope() as session:
        return list((await session.scalars(select(ForgeOutbox).order_by(ForgeOutbox.created_at))).all())


async def make_due() -> None:
    async with db.session_scope() as session:
        for row in (await session.scalars(select(ForgeOutbox).where(ForgeOutbox.status == "pending"))).all():
            row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)


def record(task_id: str | None = None, **over) -> ExecutionRecord:
    now = datetime.now(UTC)
    base = dict(
        task_id=task_id or str(uuid.uuid4()), trace_id=None, user_intent="Synthetic request", origin="interactive",
        agent_version="0.1.0", model="m", status="completed", started_at=now, finished_at=now,
    )  # fmt: skip
    return ExecutionRecord(**{**base, **over})


async def _run(app, orbit) -> tuple[httpx.AsyncClient, str, dict]:
    client = await _client(app)
    project_id = await _project(client)
    async with db.session_scope() as session:
        session.add(ProjectReference(project_id=uuid.UUID(project_id), system="orbit", external_id="forge", label="FORGE"))
    result = await _ask(client, "Create a PRD for scheduled CSV exports", project_id=project_id)
    return client, project_id, result


async def test_a_run_finished_while_forge_is_down_is_captured_once_forge_is_back_without_any_action(app, orbit, forge):
    client, _, result = await _run(app, orbit)
    task = (await client.get(f"/api/v1/tasks/{result['task_id']}")).json()
    assert task["status"] == "completed" and task["evaluation"] is None  # the user's run is not affected
    (row,) = await rows()
    assert row.status == "pending" and row.attempts == 1 and "unreachable" in row.last_error
    assert row.idempotency_key == f"nova-task:{result['task_id']}" and forge.observed == {}

    assert await maintenance.process_forge_outbox() == 0  # not due yet: the backoff is respected
    forge.error = None  # FORGE is back
    await make_due()
    assert await maintenance.process_forge_outbox() == 1
    assert list(forge.observed) == [f"nova-task:{result['task_id']}"]
    (row,) = await rows()
    assert row.status == "sent" and row.payload == {} and row.settled_at is not None
    task = (await client.get(f"/api/v1/tasks/{result['task_id']}")).json()
    assert task["evaluation"]["run_id"] == "run-1"  # linked, like a capture that worked at once

    assert await maintenance.process_forge_outbox() == 0  # and never captured again
    assert len(forge.observed) == 1


async def test_the_capture_of_a_run_is_queued_once_and_sent_once(forge):
    forge.error = None
    first = await forge_outbox.enqueue_capture(record("t-1"))
    again = await forge_outbox.enqueue_capture(record("t-1"))
    assert first == again and len(await rows()) == 1
    sink = providers.evaluation()
    results = await asyncio.gather(forge_outbox.deliver(first, sink), forge_outbox.deliver(first, sink))
    assert sorted(r or "" for r in results) == ["", "sent"]  # one worker wins the row
    assert await forge_outbox.deliver(first, sink) is None and len(forge.observed) == 1
    assert (await forge_outbox.enqueue_capture(record("t-1"))) == first and len(await rows()) == 1


async def test_a_run_already_linked_to_a_forge_run_is_marked_sent_without_sending(forge):
    forge.error = None
    from nova.domain.outputs import EvaluationReference
    from nova.services.forge_outbox import _save_reference

    await _save_reference("t-2", EvaluationReference(run_id="run-9", status="completed"), [])
    outbox_id = await forge_outbox.enqueue_capture(record("t-2"))
    assert await forge_outbox.deliver(outbox_id, providers.evaluation()) == "sent" and forge.observed == {}


async def test_failures_back_off_exponentially_then_land_in_the_failure_queue(forge, monkeypatch):
    monkeypatch.setattr(get_settings(), "forge_outbox_max_attempts", 3)
    assert [forge_outbox.backoff(n).total_seconds() for n in (1, 2, 3, 4, 20)] == [30, 60, 120, 240, 3600]
    sink = providers.evaluation()
    outbox_id = await forge_outbox.enqueue_capture(record("t-3"))
    for attempt, expected in ((1, "pending"), (2, "pending"), (3, "failed")):
        assert await forge_outbox.deliver(outbox_id, sink) == expected
        await make_due()
        (row,) = await rows()
        assert row.attempts == attempt
    assert row.status == "failed" and row.payload == {} and "unreachable" in row.last_error
    assert await maintenance.process_forge_outbox() == 0  # a failed row is not retried by itself


async def test_a_refusal_of_forge_is_final_but_a_busy_forge_is_retried(forge):
    sink = providers.evaluation()
    forge.error = ForgeError(422, "invalid scenario")
    refused = await forge_outbox.enqueue_capture(record("t-4"))
    assert await forge_outbox.deliver(refused, sink) == "failed"
    forge.error = ForgeError(429, "too many requests")
    busy = await forge_outbox.enqueue_capture(record("t-5"))
    assert await forge_outbox.deliver(busy, sink) == "pending"


async def test_a_secret_run_is_skipped_with_its_reason_and_waits_with_no_text(forge, monkeypatch):
    monkeypatch.setattr(get_settings(), "forge_capture_mode", "reexecute")
    secret = record(
        "t-6", user_intent="SYNTHETIC-C3-REQUEST", context_max_classification=3,
        context_documents=[{"id": "S1", "title": "Plan", "content": "SYNTHETIC-C3-EXCERPT", "source": "orbit", "classification": 3}],
    )  # fmt: skip
    outbox_id = await forge_outbox.enqueue_capture(secret)
    (row,) = await rows()
    assert "SYNTHETIC-C3" not in str(row.payload)  # nothing readable waits in the outbox above the ceiling
    assert await forge_outbox.deliver(outbox_id, providers.evaluation()) == "skipped"
    (row,) = await rows()
    assert row.status == "skipped" and "C3" in row.last_error and forge.attempts == 0


async def test_unhelpful_feedback_while_forge_is_down_is_delivered_later_without_action(app, orbit, forge, monkeypatch):
    monkeypatch.setattr(get_settings(), "forge_capture_policy", "on_feedback")
    monkeypatch.setattr(get_settings(), "forge_capture_mode", "reexecute")
    monkeypatch.setattr(get_settings(), "forge_nova_endpoint", "https://nova-api.example")
    monkeypatch.setattr(get_settings(), "forge_credential_id", "configured-credential")
    client, _, result = await _run(app, orbit)
    response = await client.post(
        "/api/v1/feedback", json={"rating": "not_useful", "comment": "Vague", "message_id": result["reply"]["id"]}
    )
    assert response.status_code == 201 and response.json()["forwarded"]["forge"] == "pending"
    (row,) = await rows()
    assert row.status == "pending" and row.payload["feedback"][0]["comment"] == "Vague"
    forge.error = None
    await make_due()
    assert await maintenance.process_forge_outbox() == 1
    async with db.session_scope() as session:
        reference = await session.scalar(select(IntegrationReference).where(IntegrationReference.nova_id == result["task_id"]))
    assert reference.data["run_id"] and reference.data["pending_feedback"][0]["comment"] == "Vague"


async def test_the_queue_state_is_visible_to_administrators_and_to_prometheus(app, forge):
    await forge_outbox.enqueue_capture(record("t-7"))
    done = await forge_outbox.enqueue_capture(record("t-8"))
    forge.error = None
    await forge_outbox.deliver(done, providers.evaluation())
    admin = await _client(app, "admin-outbox@example.com")
    async with db.session_scope() as session:
        user = await session.scalar(select(User).where(User.email == "admin-outbox@example.com"))
        user.is_admin = True
    state = (await admin.get("/api/v1/admin/forge-outbox")).json()
    assert (state["pending"], state["sent"], state["failed"], state["skipped"]) == (1, 1, 0, 0)
    assert state["oldest_waiting_seconds"] >= 0
    text = (await admin.get("/api/v1/admin/forge-outbox/metrics")).text
    assert 'nova_forge_outbox_rows{status="pending"} 1' in text and "nova_forge_outbox_oldest_waiting_seconds" in text
    member = await _client(app)
    assert (await member.get("/api/v1/admin/forge-outbox")).status_code == 403
    assert (await member.get("/api/v1/admin/forge-outbox/metrics")).status_code == 403
