"""Replay: a finished run re-executed as a new task with other context / model / lessons."""

from __future__ import annotations

import uuid

import httpx
import pytest_asyncio
from sqlalchemy import select

from nova.config import get_settings
from nova.domain.outputs import IntentClassification
from nova.infra import db
from nova.infra.models import Artifact, ProjectReference, Task
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


async def _run(client: httpx.AsyncClient, llm) -> str:
    llm.intent = lambda m: IntentClassification(
        kind="run_workflow", goal="PRD", candidate_skill_ids=["prd"], context_query="scheduled CSV exports"
    )
    r = await client.post("/api/v1/projects", json={"name": f"FORGE {uuid.uuid4().hex[:4]}", "description": "x"})
    pid = r.json()["id"]
    async with db.session_scope() as session:
        session.add(ProjectReference(project_id=uuid.UUID(pid), system="orbit", external_id="forge", label="FORGE"))
    conversation = (await client.post("/api/v1/conversations", json={})).json()
    r = await client.post(
        f"/api/v1/conversations/{conversation['id']}/messages", json={"text": "Create a PRD for CSV exports", "project_id": pid}
    )
    assert r.status_code == 202, r.text
    return r.json()["task"]["id"]


async def _task(task_id: str) -> Task:
    async with db.session_scope() as session:
        return await session.get(Task, uuid.UUID(task_id))


async def test_replay_reuses_the_original_context_and_links_back(app, llm, orbit, forge):
    client = await _client(app)
    original = await _run(client, llm)
    assert (await _task(original)).status == "completed"
    served = len(orbit.queries)

    r = await client.post(f"/api/v1/executions/{original}/replay", json={})
    assert r.status_code == 202, r.text
    replay_id = r.json()["id"]
    assert len(orbit.queries) == served  # the same sources, no new ORBIT retrieval

    replay = await _task(replay_id)
    assert replay.status == "completed" and replay.replay_of == uuid.UUID(original) and replay.origin == "replay"
    assert replay.conversation_id is None and replay.run_manifest["replay_of"] == original
    assert replay.run_manifest["overrides"] == {"context": "original"}
    assert replay.run_manifest["context"]["items"] == (await _task(original)).run_manifest["context"]["items"] > 0
    assert forge.captured == []  # a replay is never captured into FORGE as production traffic

    listed = (await client.get(f"/api/v1/executions/{original}/replays")).json()
    assert [x["id"] for x in listed] == [replay_id] and listed[0]["overrides"] == {"context": "original"}
    # The original is untouched and the replay's artifact is its own
    async with db.session_scope() as session:
        owners = set(
            await session.scalars(select(Artifact.task_id).where(Artifact.task_id.in_([uuid.UUID(original), replay.id])))
        )
    assert owners == {uuid.UUID(original), replay.id}


async def test_live_replay_queries_orbit_again(app, llm, orbit, forge):
    client = await _client(app)
    original = await _run(client, llm)
    served = len(orbit.queries)
    r = await client.post(f"/api/v1/executions/{original}/replay", json={"context": "live"})
    assert r.status_code == 202 and len(orbit.queries) == served + 1
    assert (await _task(r.json()["id"])).run_manifest["overrides"]["context"] == "live"


async def test_replay_without_context(app, llm, orbit, forge):
    client = await _client(app)
    original = await _run(client, llm)
    served = len(orbit.queries)
    r = await client.post(f"/api/v1/executions/{original}/replay", json={"context": "none"})
    assert r.status_code == 202 and len(orbit.queries) == served
    assert (await _task(r.json()["id"])).run_manifest["context"]["items"] == 0


async def test_model_must_be_on_the_allow_list_and_is_applied(app, llm, orbit, forge, monkeypatch):
    client = await _client(app)
    original = await _run(client, llm)
    refused = await client.post(f"/api/v1/executions/{original}/replay", json={"model": "pricey-model"})
    assert refused.status_code == 422 and refused.json()["code"] == "model_not_allowed"

    monkeypatch.setattr(get_settings(), "replay_models", ["cheap-model"])
    built: list[str] = []

    def fake_build(settings):
        built.append(settings.llm_model)
        return llm

    monkeypatch.setattr("nova.services.executions.build_llm_provider", fake_build)
    ok = await client.post(f"/api/v1/executions/{original}/replay", json={"model": "cheap-model"})
    assert ok.status_code == 202 and built == ["cheap-model"]
    assert (await _task(ok.json()["id"])).run_manifest["overrides"]["model"] == "cheap-model"


async def test_replay_guards(app, llm, orbit, forge):
    client = await _client(app)
    original = await _run(client, llm)
    other = await _client(app)
    assert (await other.post(f"/api/v1/executions/{original}/replay", json={})).status_code in (403, 404)
    bad = await client.post(f"/api/v1/executions/{original}/replay", json={"snapshot": {"name": "s"}})
    assert bad.status_code == 422  # a snapshot needs live context
    async with db.session_scope() as session:
        task = await session.get(Task, uuid.UUID(original))
        task.status = "running"
    busy = await client.post(f"/api/v1/executions/{original}/replay", json={})
    assert busy.status_code == 409


async def test_compare_puts_a_run_and_its_replay_side_by_side(app, llm, orbit, forge):
    client = await _client(app)
    original = await _run(client, llm)
    replay = (await client.post(f"/api/v1/executions/{original}/replay", json={"context": "none"})).json()["id"]

    body = (await client.get(f"/api/v1/executions/{original}/compare/{replay}")).json()
    assert body["original"]["id"] == original and body["replay"]["id"] == replay
    assert body["original"]["context_items"] > 0 and body["replay"]["context_items"] == 0
    assert body["replay"]["overrides"] == {"context": "none"}
    assert body["delta"]["context_items"] == -1.0
    assert [a["type"] for a in body["artifacts"]] and all({"words", "sections"} <= a.keys() for a in body["artifacts"])

    other = (await client.post(f"/api/v1/executions/{original}/replay", json={})).json()["id"]
    unrelated = await _run(client, llm)
    refused = await client.get(f"/api/v1/executions/{unrelated}/compare/{other}")
    assert refused.status_code == 422 and refused.json()["code"] == "not_a_replay"
    stranger = await _client(app)
    assert (await stranger.get(f"/api/v1/executions/{original}/compare/{replay}")).status_code in (403, 404)


async def test_replay_options_list_the_models_and_lessons_a_what_if_can_change(app, monkeypatch):
    monkeypatch.setattr(get_settings(), "replay_models", ["cheap-model"])
    client = await _client(app)
    body = (await client.get("/api/v1/executions/replay/options")).json()
    assert body["models"] == ["cheap-model"] and isinstance(body["policies"], list)
