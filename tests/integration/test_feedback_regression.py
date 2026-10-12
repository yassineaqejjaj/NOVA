"""A click on "not useful" becomes a regression test in FORGE - only when the user asks and the policy allows it."""

from __future__ import annotations

import uuid

import pytest_asyncio
from sqlalchemy import select

from nova.config import get_settings
from nova.infra import db
from nova.infra.models import AuditEvent, ContextRetrievalReference, Feedback, IntegrationReference
from nova.integrations.forge.client import ForgeError
from nova_api.main import create_app
from tests.integration.test_api import _ask, _client, _project


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


async def _unhelpful(client) -> tuple[str, str]:
    """Rate a fresh answer "not useful" (captured in FORGE, still pending): ``(feedback_id, task_id)``."""
    project_id = await _project(client)
    from nova.infra.models import ProjectReference

    async with db.session_scope() as session:
        session.add(ProjectReference(project_id=uuid.UUID(project_id), system="orbit", external_id="forge", label="FORGE"))
    result = await _ask(client, "Create a PRD for scheduled CSV exports", project_id=project_id)
    response = await client.post(
        "/api/v1/feedback",
        json={"rating": "not_useful", "comment": "Metrics are vague", "message_id": result["reply"]["id"]},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"], result["task_id"]


async def _evaluated(task_id: str) -> None:
    """What the refresh job does once FORGE has scored the run."""
    async with db.session_scope() as session:
        row = await session.scalar(
            select(IntegrationReference).where(IntegrationReference.nova_type == "task", IntegrationReference.nova_id == task_id)
        )
        assert row is not None
        row.data = {**row.data, "status": "completed"}


async def test_an_unhelpful_answer_becomes_a_regression_test_once_forge_has_evaluated_it(app, orbit, forge):
    client = await _client(app)
    feedback_id, task_id = await _unhelpful(client)

    early = await client.post(f"/api/v1/feedback/{feedback_id}/regression")
    assert early.status_code == 409 and early.json()["code"] == "not_evaluated" and forge.promoted == []

    await _evaluated(task_id)
    created = await client.post(f"/api/v1/feedback/{feedback_id}/regression")
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["created"] is True and body["slug"].startswith("regression-") and body["url"].endswith(body["scenario_id"])
    again = (await client.post(f"/api/v1/feedback/{feedback_id}/regression")).json()
    assert again["created"] is False  # idempotent: the same case, not a second one

    async with db.session_scope() as session:
        row = await session.get(Feedback, uuid.UUID(feedback_id))
        assert row is not None and row.forwarded["regression"]["slug"] == body["slug"]
        audited = await session.scalar(select(AuditEvent).where(AuditEvent.action == "feedback.regression"))
        assert audited is not None


async def test_it_is_refused_when_the_organization_does_not_send_requests_to_forge(app, orbit, forge, monkeypatch):
    client = await _client(app)
    feedback_id, task_id = await _unhelpful(client)
    await _evaluated(task_id)
    monkeypatch.setattr(get_settings(), "forge_capture_mode", "observed")
    monkeypatch.setattr(get_settings(), "forge_capture_intent", False)
    refused = await client.post(f"/api/v1/feedback/{feedback_id}/regression")
    assert refused.status_code == 409 and refused.json()["code"] == "request_not_shared" and forge.promoted == []
    monkeypatch.setattr(get_settings(), "forge_capture_intent", True)
    assert (await client.post(f"/api/v1/feedback/{feedback_id}/regression")).status_code == 200


async def test_it_is_refused_for_a_run_that_used_confidential_or_secret_context(app, orbit, forge):
    client = await _client(app)
    feedback_id, task_id = await _unhelpful(client)
    await _evaluated(task_id)
    async with db.session_scope() as session:
        refs = (
            await session.scalars(
                select(ContextRetrievalReference).where(ContextRetrievalReference.task_id == uuid.UUID(task_id))
            )
        ).all()
        assert refs, "the run served context"
        refs[0].max_classification = 2
    refused = await client.post(f"/api/v1/feedback/{feedback_id}/regression")
    assert refused.status_code == 409 and refused.json()["code"] == "classified_context" and forge.promoted == []


async def test_only_the_author_can_do_it_and_only_for_unhelpful_answers(app, orbit, forge):
    client = await _client(app)
    feedback_id, task_id = await _unhelpful(client)
    await _evaluated(task_id)
    stranger = await _client(app)
    assert (await stranger.post(f"/api/v1/feedback/{feedback_id}/regression")).status_code in (403, 404)
    assert (await client.post("/api/v1/feedback/not-a-uuid/regression")).status_code in (403, 404)

    result = await _ask(client, "Create a PRD for audit logs")
    useful = await client.post("/api/v1/feedback", json={"rating": "useful", "message_id": result["reply"]["id"]})
    refused = await client.post(f"/api/v1/feedback/{useful.json()['id']}/regression")
    assert refused.status_code == 409 and refused.json()["code"] == "not_applicable"


async def test_forge_refusing_the_case_is_explained_not_hidden(app, orbit, forge):
    client = await _client(app)
    feedback_id, task_id = await _unhelpful(client)
    await _evaluated(task_id)
    forge.promote_error = ForgeError(422, "Seuls les runs en échec ou non réussis peuvent devenir des cas de régression")
    refused = await client.post(f"/api/v1/feedback/{feedback_id}/regression")
    assert refused.status_code == 409 and refused.json()["code"] == "refused"
    assert "cas de régression" in refused.json()["detail"]
