"""ORBIT snapshots: list / preview / reference through the API, and the reference applied by the agents."""

from __future__ import annotations

import uuid

import httpx
import pytest_asyncio
from sqlalchemy import select

from nova.domain.context import ContextError, SnapshotRef
from nova.infra import db
from nova.infra.models import ContextRetrievalReference, ProjectReference
from nova.services.conversations import ComposerInput, create_conversation, submit
from nova.services.executions import run_task
from nova.skills.registry import get_skill_registry
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


async def _linked_project(client: httpx.AsyncClient) -> str:
    r = await client.post("/api/v1/projects", json={"name": f"FORGE {uuid.uuid4().hex[:4]}", "description": "x"})
    pid = r.json()["id"]
    async with db.session_scope() as session:
        session.add(ProjectReference(project_id=uuid.UUID(pid), system="orbit", external_id="forge", label="FORGE"))
    return pid


async def test_list_preview_set_and_unset_the_reference(app, orbit):
    client = await _client(app)
    pid = await _linked_project(client)
    listed = (await client.get("/api/v1/context/snapshots", params={"project_id": pid})).json()
    assert listed["snapshots"][0]["name"] == "release-plan" and listed["reference"] is None
    preview = (await client.get("/api/v1/context/snapshots/release-plan", params={"project_id": pid, "version": 2})).json()
    assert preview["snapshot"]["version"] == 2 and preview["snapshot"]["items"][0]["citation"] == "S1"

    put = await client.put("/api/v1/context/snapshots/reference", json={"project_id": pid, "name": "release-plan"})
    assert put.status_code == 200 and put.json()["reference"] == {"name": "release-plan", "version": None}
    assert (await client.get("/api/v1/context/snapshots", params={"project_id": pid})).json()["reference"][
        "name"
    ] == "release-plan"
    await client.put("/api/v1/context/snapshots/reference", json={"project_id": pid, "name": "release-plan", "version": 1})
    assert (await client.get("/api/v1/context/snapshots", params={"project_id": pid})).json()["reference"]["version"] == 1

    assert (await client.delete("/api/v1/context/snapshots/reference", params={"project_id": pid})).json()["reference"] is None
    assert (await client.get("/api/v1/context/snapshots", params={"project_id": pid})).json()["reference"] is None


async def test_errors_are_mapped_and_a_stranger_has_no_access(app, orbit):
    client, stranger = await _client(app), await _client(app)
    pid = await _linked_project(client)
    unknown = await client.put("/api/v1/context/snapshots/reference", json={"project_id": pid, "name": "ghost"})
    assert unknown.status_code == 404
    orbit.snapshot_error = ContextError("not_linked", "ORBIT is not connected for this user")
    r = await client.get("/api/v1/context/snapshots", params={"project_id": pid})
    assert "orbit_not_linked" in r.text
    orbit.snapshot_error = ContextError("unauthorized", "expired")
    assert "orbit_unauthorized" in (await client.get("/api/v1/context/snapshots", params={"project_id": pid})).text
    assert (await stranger.get("/api/v1/context/snapshots", params={"project_id": pid})).status_code in (403, 404)


async def _start_task(user, project_id: str, text: str) -> str:
    async with db.session_scope() as session:
        conversation = await create_conversation(session, user, project_id=project_id, title=None)
        _, _, task = await submit(
            session,
            user,
            conversation,
            ComposerInput(text=text, project_id=project_id),
            {s.id for s in get_skill_registry().all()},
        )
        return str(task.id)


async def test_agents_apply_the_reference_snapshot_and_record_it(user, project, orbit):
    from nova.services import orbit_snapshots

    await orbit_snapshots.set_reference(user.user_id, "forge", SnapshotRef(name="release-plan", version=2))
    task_id = await _start_task(user, project, "Create a PRD for scheduled CSV exports in FORGE")
    assert await run_task(task_id, "start") == "completed"
    assert orbit.queries[0].base_snapshot == SnapshotRef(name="release-plan", version=2)
    async with db.session_scope() as session:
        ref = await session.scalar(
            select(ContextRetrievalReference).where(ContextRetrievalReference.task_id == uuid.UUID(task_id))
        )
        assert (ref.snapshot_name, ref.snapshot_version) == ("release-plan", 2)


async def test_a_disabled_or_missing_reference_sends_no_base_snapshot(user, project, orbit):
    task_id = await _start_task(user, project, "Create a PRD for scheduled CSV exports in FORGE")
    assert await run_task(task_id, "start") == "completed"
    assert orbit.queries[0].base_snapshot is None


async def test_an_unusable_snapshot_degrades_to_a_plain_retrieval_with_a_warning(user, project, orbit):
    from nova.services import orbit_snapshots

    await orbit_snapshots.set_reference(user.user_id, "forge", SnapshotRef(name="release-plan"))
    orbit.snapshot_error = ContextError("not_found", "Snapshot not found")
    task_id = await _start_task(user, project, "Create a PRD for scheduled CSV exports in FORGE")
    assert await run_task(task_id, "start") == "completed"
    assert [q.base_snapshot is not None for q in orbit.queries[:2]] == [True, False]
    async with db.session_scope() as session:
        ref = await session.scalar(
            select(ContextRetrievalReference).where(ContextRetrievalReference.task_id == uuid.UUID(task_id))
        )
        assert any("release-plan" in w and "no longer available" in w for w in ref.warnings)
        assert ref.snapshot_name is None and ref.items
