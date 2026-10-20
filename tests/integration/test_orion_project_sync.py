"""ORBIT's ``orion_project_id`` (NOV-106) is recorded on the NOVA project linked to the ORBIT project (ADR 001 §5, NOV-107)."""

from __future__ import annotations

import uuid

import httpx
import pytest_asyncio
from sqlalchemy import select

from nova.domain.context import ContextBundle, ContextProjectInfo, ContextSnapshot
from nova.domain.llm_guardrail import CallScope
from nova.infra import db
from nova.infra.models import AuditEvent, Project, ProjectReference
from nova.integrations.orbit.mapper import context_bundle, project_info, snapshot
from nova.services import projects, workspaces
from nova.services.execution_store import SqlExecutionStore
from nova_api.main import create_app


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


def _projects(orbit, *infos: ContextProjectInfo) -> None:
    async def list_projects(user_id: str) -> list[ContextProjectInfo]:
        return list(infos)

    orbit.list_projects = list_projects


def _slug() -> str:
    return f"orbit-{uuid.uuid4().hex[:8]}"


async def _linked(slug: str) -> tuple[uuid.UUID, uuid.UUID | None, uuid.UUID | None]:
    """(project id, project's ORION id, reference's ORION id) of the NOVA project linked to the ORBIT project ``slug``."""
    async with db.session_scope() as session:
        project, reference = (
            await session.execute(
                select(Project, ProjectReference)
                .join(ProjectReference, ProjectReference.project_id == Project.id)
                .where(ProjectReference.system == "orbit", ProjectReference.external_id == slug)
            )
        ).one()
        return project.id, project.orion_project_id, reference.orion_project_id


async def _conflicts(project_id: uuid.UUID) -> list[AuditEvent]:
    async with db.session_scope() as session:
        return list(
            (
                await session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.action == "project.orion_id_conflict", AuditEvent.project_id == project_id
                    )
                )
            ).all()
        )


# --- the mapping of ORBIT's payloads --------------------------------------------------------------------------------------------


def test_orion_project_id_is_read_from_projects_context_and_snapshots_and_never_served_to_the_browser():
    orion = str(uuid.uuid4())
    info = project_info({"id": "1", "slug": "forge", "name": "FORGE", "orion_project_id": orion})
    bundle = context_bundle({"request_id": "r", "orion_project_id": orion}, "forge", "http://orbit")
    snap = snapshot({"name": "plan", "version": 1, "orion_project_id": orion})
    assert (info.orion_project_id, bundle.orion_project_id, snap.orion_project_id) == (orion, orion, orion)
    for model in (info, bundle, snap):
        assert "orion_project_id" not in model.model_dump(mode="json")  # the responses of the API are unchanged
    older = project_info({"id": "1", "slug": "forge", "name": "FORGE"})
    assert older.orion_project_id is None and context_bundle({"request_id": "r"}, "forge", "http://o").orion_project_id is None


# --- alignment at the link ------------------------------------------------------------------------------------------------------


async def test_syncing_the_orbit_projects_records_their_orion_id_and_never_overwrites_a_divergent_one(user, orbit):
    slug, first, other = _slug(), uuid.uuid4(), uuid.uuid4()
    _projects(orbit, ContextProjectInfo(slug=slug, name="Alpha", orion_project_id=str(first)))
    async with db.session_scope() as session:
        assert await projects.sync_from_orbit(session, user) == 1
    project_id, project_value, reference_value = await _linked(slug)
    assert project_value == reference_value == first  # the placeholder NOVA minted gave way to ORBIT's id

    async with db.session_scope() as session:  # the same report again changes nothing
        await projects.sync_from_orbit(session, user)
    assert await _linked(slug) == (project_id, first, first) and await _conflicts(project_id) == []

    _projects(orbit, ContextProjectInfo(slug=slug, name="Alpha", orion_project_id=str(other)))  # ORBIT now says something else
    async with db.session_scope() as session:
        await projects.sync_from_orbit(session, user)
    assert await _linked(slug) == (project_id, first, first)  # the recorded value stands
    conflicts = await _conflicts(project_id)
    assert (
        len(conflicts) == 1 and conflicts[0].details["reported"] == str(other) and conflicts[0].details["recorded"] == str(first)
    )


async def test_an_id_another_project_holds_is_a_logged_conflict_and_an_unusable_one_is_ignored(user, orbit):
    one, two, shared = _slug(), _slug(), uuid.uuid4()
    _projects(
        orbit,
        ContextProjectInfo(slug=one, name="One", orion_project_id=str(shared)),
        ContextProjectInfo(slug=two, name="Two", orion_project_id=str(shared)),  # the same ORION id twice: one of them is wrong
    )
    async with db.session_scope() as session:
        await projects.sync_from_orbit(session, user)
    (_, value_one, _), (id_two, value_two, ref_two) = await _linked(one), await _linked(two)
    assert value_one == shared and value_two != shared and ref_two is None  # the second keeps its own, nothing is merged
    assert len(await _conflicts(id_two)) == 1

    third = _slug()
    _projects(orbit, ContextProjectInfo(slug=third, name="Three", orion_project_id="not-a-uuid"))
    async with db.session_scope() as session:
        await projects.sync_from_orbit(session, user)
    _, value, reference = await _linked(third)
    assert value is not None and reference is None  # kept its own, no id recorded


async def test_a_project_linked_without_an_orbit_id_keeps_working(user, orbit, project):
    async with db.session_scope() as session:
        before = (await session.get(Project, uuid.UUID(project))).orion_project_id
        assert (await workspaces.sync_orion_project_id_by_slug(session, "forge", None))["aligned"] == 0
        assert (await session.get(Project, uuid.UUID(project))).orion_project_id == before


# --- alignment from the context ORBIT serves ------------------------------------------------------------------------------------


async def test_the_context_orbit_serves_aligns_the_linked_project(user):
    orion, slug = uuid.uuid4(), _slug()
    async with db.session_scope() as session:
        linked = Project(slug=f"p-{uuid.uuid4().hex[:6]}", name="Linked")
        session.add(linked)
        await session.flush()
        session.add(ProjectReference(project_id=linked.id, system="orbit", external_id=slug))
        project = str(linked.id)
    store = SqlExecutionStore(user, scope=CallScope())
    bundle = ContextBundle(retrieval_id="r-1", project_slug=slug, orion_project_id=str(orion))
    await store.record_context(task_id=None, user_id=user.user_id, conversation_id=None, query="q", bundle=bundle)
    async with db.session_scope() as session:
        reference = await session.scalar(select(ProjectReference).where(ProjectReference.project_id == uuid.UUID(project)))
        assert reference.orion_project_id == orion
        assert (await session.get(Project, uuid.UUID(project))).orion_project_id == orion
    other = ContextBundle(retrieval_id="r-2", project_slug=slug, orion_project_id=str(uuid.uuid4()))
    await store.record_context(task_id=None, user_id=user.user_id, conversation_id=None, query="q", bundle=other)
    async with db.session_scope() as session:
        assert (await session.get(Project, uuid.UUID(project))).orion_project_id == orion  # never overwritten
    await store.record_context(task_id=None, user_id=user.user_id, conversation_id=None, query="q", bundle=other)
    assert len(await _conflicts(uuid.UUID(project))) == 1  # the same report is on record once


async def test_reading_a_snapshot_aligns_the_linked_project_and_the_response_is_unchanged(app, orbit, monkeypatch):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    assert (
        await client.post("/api/v1/auth/dev-login", json={"email": f"{uuid.uuid4().hex[:8]}@example.com", "name": "S"})
    ).status_code == 200
    created = (await client.post("/api/v1/projects", json={"name": f"P {uuid.uuid4().hex[:4]}", "description": "x"})).json()
    slug, orion = _slug(), uuid.uuid4()
    async with db.session_scope() as session:
        session.add(ProjectReference(project_id=uuid.UUID(created["id"]), system="orbit", external_id=slug))

    async def get_snapshot(user_id, project_slug, name, version=None) -> ContextSnapshot:
        return ContextSnapshot(name=name, version=1, orion_project_id=str(orion))

    monkeypatch.setattr(orbit, "get_snapshot", get_snapshot)
    response = await client.get("/api/v1/context/snapshots/plan", params={"project_id": created["id"]})
    assert response.status_code == 200 and "orion_project_id" not in response.text
    assert (await _linked(slug))[1:] == (orion, orion)
