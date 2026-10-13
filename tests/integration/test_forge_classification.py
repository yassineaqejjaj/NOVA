"""A run FORGE starts keeps the classification and the ORBIT context FORGE handed over (synthetic data only)."""

from __future__ import annotations

import uuid

import httpx
import pytest_asyncio
from sqlalchemy import select

from nova.config import get_settings
from nova.infra import db
from nova.infra.models import Artifact, ContextRetrievalReference, ProjectReference, Task
from nova_api.main import create_app


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


async def _run(app, context: dict) -> httpx.Response:
    body = {"input": {"prompt": "Write a PRD for the synthetic export feature."}, "context": context}
    headers = {"Authorization": f"Bearer {get_settings().forge_inbound_token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as forge:
        return await forge.post("/v1/agents/nova-orchestrator/runs", json=body, headers=headers)


async def _task_records(task_id: str):
    async with db.session_scope() as session:
        task = await session.get(Task, uuid.UUID(task_id))
        artifacts = (await session.scalars(select(Artifact).where(Artifact.task_id == task.id))).all()
        refs = (
            await session.scalars(select(ContextRetrievalReference).where(ContextRetrievalReference.task_id == task.id))
        ).all()
        return task.input["provided_context"], [a.classification for a in artifacts], [r.max_classification for r in refs]


async def test_a_secret_document_makes_the_run_its_artifacts_and_its_context_record_secret(app):
    response = await _run(
        app,
        {
            "documents": [
                {"id": "d1", "title": "Synthetic plan", "content": "synthetic", "source": "orbit", "classification": 3},
                {"id": "d2", "title": "Synthetic note", "content": "synthetic", "source": "orbit", "classification": 1},
            ],
            "orbit_context": {"max_classification": 3},
        },
    )
    data = response.json()
    assert response.status_code == 200 and data.get("error") is None
    provided, artifact_levels, record_levels = await _task_records(data["metadata"]["nova_task_id"])
    assert [i["classification"] for i in provided] == [3, 3]
    assert artifact_levels and set(artifact_levels) == {3}
    assert record_levels == [3]


async def test_a_document_without_classification_is_handled_as_secret(app):
    response = await _run(app, {"documents": [{"id": "d1", "title": "Unlabelled", "content": "synthetic"}]})
    provided, artifact_levels, record_levels = await _task_records(response.json()["metadata"]["nova_task_id"])
    assert [i["classification"] for i in provided] == [3] and set(artifact_levels) == {3} and record_levels == [3]


async def test_a_public_document_stays_public(app):
    response = await _run(app, {"documents": [{"id": "d1", "title": "Open", "content": "synthetic", "classification": 0}]})
    provided, artifact_levels, _ = await _task_records(response.json()["metadata"]["nova_task_id"])
    assert [i["classification"] for i in provided] == [0] and set(artifact_levels) == {0}


async def test_context_above_the_policy_ceiling_is_refused_before_any_run(app, monkeypatch):
    monkeypatch.setattr(get_settings(), "policy_max_classification", 2)
    response = await _run(app, {"documents": [{"id": "d1", "content": "synthetic", "classification": 3}]})
    assert response.status_code == 403 and response.json()["error"]["type"] == "CLASSIFICATION_REFUSED"
    assert "d1" in response.json()["error"]["message"]
    ok = await _run(app, {"documents": [{"id": "d1", "content": "synthetic", "classification": 2}]})
    assert ok.status_code == 200


async def test_the_orbit_context_text_reaches_the_model(app, llm):
    marker = "SYNTHETIC-ORBIT-CONTEXT-MARKER"
    response = await _run(app, {"orbit_context": f"Assembled context: {marker}", "max_classification": 1})
    assert response.status_code == 200 and response.json().get("error") is None
    assert any(marker in m.content for _, messages in llm.calls for m in messages)


async def test_a_captured_run_hands_the_classification_of_each_document_to_the_evaluation_sink(app, orbit, forge, monkeypatch):

    from tests.support.fakes import context_item

    from .test_api import _ask, _client, _project

    orbit.items = [context_item(1, "Synthetic open note", classification=1), context_item(2, "Synthetic plan", classification=3)]
    monkeypatch.setattr(get_settings(), "forge_capture_policy", "all")
    client = await _client(app)
    project_id = await _project(client)
    async with db.session_scope() as session:
        session.add(ProjectReference(project_id=uuid.UUID(project_id), system="orbit", external_id="forge", label="FORGE"))
    result = await _ask(client, "Create a PRD for scheduled CSV exports", project_id=project_id)
    (record,) = [r for r in forge.captured if r.task_id == result["task_id"]]
    assert [d["classification"] for d in record.context_documents] == [1, 3] and record.context_max_classification == 3
