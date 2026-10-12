"""Living Artifacts: an Artifact knows when what it cites has changed, and proposes the update."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest_asyncio
from sqlalchemy import select

from nova.domain.context import ContextChange, ContextError
from nova.domain.outputs import IntentClassification
from nova.infra import db
from nova.infra.models import Artifact, ProjectReference
from nova_api.main import create_app


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


async def _client(app) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    r = await client.post(
        "/api/v1/auth/dev-login", json={"email": f"{uuid.uuid4().hex[:8]}@example.com", "name": "Y", "title": "PM"}
    )
    assert r.status_code == 200
    return client


async def _artifact(client: httpx.AsyncClient, llm) -> str:
    llm.intent = lambda m: IntentClassification(
        kind="run_workflow", goal="PRD", candidate_skill_ids=["prd"], context_query="scheduled CSV exports"
    )
    pid = (await client.post("/api/v1/projects", json={"name": f"FORGE {uuid.uuid4().hex[:4]}", "description": "x"})).json()["id"]
    async with db.session_scope() as session:
        session.add(ProjectReference(project_id=uuid.UUID(pid), system="orbit", external_id="forge", label="FORGE"))
    conversation = (await client.post("/api/v1/conversations", json={})).json()
    r = await client.post(
        f"/api/v1/conversations/{conversation['id']}/messages", json={"text": "Create a PRD for CSV exports", "project_id": pid}
    )
    task_id = uuid.UUID(r.json()["task"]["id"])
    async with db.session_scope() as session:
        return str(await session.scalar(select(Artifact.id).where(Artifact.task_id == task_id)))


def _change(target: str, *, type_: str = "memory.superseded", slug: str = "forge") -> ContextChange:
    return ContextChange(
        id=f"chg-{uuid.uuid4().hex[:6]}",
        project_slug=slug,
        type=type_,
        type_label="Decision superseded",
        title="Q4 goals were revised",
        target_id=target,
        created_at=datetime.now(UTC) + timedelta(minutes=5),
    )


async def test_an_artifact_is_fresh_until_something_it_cites_changes(app, llm, orbit, forge):
    client = await _client(app)
    artifact_id = await _artifact(client, llm)

    before = (await client.get(f"/api/v1/artifacts/{artifact_id}/freshness")).json()
    assert before["status"] == "fresh" and before["sources"] >= 1 and before["impacts"] == []

    orbit.changes = [_change("chunk-1"), _change("chunk-404"), _change("chunk-1", slug="elsewhere")]
    after = (await client.get(f"/api/v1/artifacts/{artifact_id}/freshness")).json()
    assert after["status"] == "stale" and after["stale_sections"]
    assert [i["type"] for i in after["impacts"]] == ["memory.superseded"]  # only the change that touches a cited source


async def test_context_being_unreachable_is_unverified_not_fresh(app, llm, orbit, forge):
    client = await _client(app)
    artifact_id = await _artifact(client, llm)

    async def down(*_args, **_kwargs):
        raise ContextError("unavailable", "ORBIT is down")

    orbit.recent_changes = down
    body = (await client.get(f"/api/v1/artifacts/{artifact_id}/freshness")).json()
    assert body["status"] == "unverified" and body["reason"] == "context_unavailable"


async def test_refresh_proposes_an_update_only_when_a_source_changed(app, llm, orbit, forge):
    client = await _client(app)
    artifact_id = await _artifact(client, llm)
    assert (await client.post(f"/api/v1/artifacts/{artifact_id}/refresh")).status_code == 409

    orbit.changes = [_change("chunk-1")]
    started = await client.post(f"/api/v1/artifacts/{artifact_id}/refresh")
    assert started.status_code == 202 and started.json()["task_id"]

    stranger = await _client(app)
    assert (await stranger.get(f"/api/v1/artifacts/{artifact_id}/freshness")).status_code in (403, 404)
    assert (await stranger.post(f"/api/v1/artifacts/{artifact_id}/refresh")).status_code in (403, 404)
