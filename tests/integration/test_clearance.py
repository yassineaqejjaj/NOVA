"""Clearance on the principal: derived Artifacts are as sensitive as their sources (NOV-75).

Synthetic fixtures only: the "secret" content below is a made-up marker, never real data.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

import httpx
import pytest_asyncio
from sqlalchemy import select

from nova.artifacts.registry import get_artifact_registry
from nova.domain.artifacts import Citation, TextBlock, empty_content
from nova.domain.context import ContextItem
from nova.infra import db
from nova.infra.models import (
    Artifact,
    ArtifactVersion,
    ContextRetrievalReference,
    OrbitAccount,
    Project,
    ProjectMember,
    Task,
    User,
)
from nova.services.access import AccessDenied, require_artifact
from nova.services.execution_store import SqlExecutionStore
from nova.services.users import principal_for
from nova_api.main import create_app

MARKER = "SYNTHETIC-C3-MARKER"


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


async def _client(app, name: str) -> tuple[httpx.AsyncClient, str]:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    response = await client.post(
        "/api/v1/auth/dev-login", json={"email": f"{name}-{uuid.uuid4().hex[:6]}@example.com", "name": name, "title": "QA"}
    )
    assert response.status_code == 200, response.text
    return client, (await client.get("/api/v1/me")).json()["id"]


async def _clearance(user_id: str, level: int) -> None:
    async with db.session_scope() as session:
        session.add(OrbitAccount(user_id=uuid.UUID(user_id), orbit_user_id="o-1", orbit_email="o@example.com", clearance=level))


async def _artifact(owner_id: str, viewer_id: str | None, *, level: int, role: str = "viewer") -> str:
    """A PRD of classification ``level`` in a project where the viewer (if any) has ``role``."""
    async with db.session_scope() as session:
        project = Project(slug=f"p-{uuid.uuid4().hex[:6]}", name="Secret project")
        session.add(project)
        await session.flush()
        session.add(ProjectMember(project_id=project.id, user_id=uuid.UUID(owner_id), role="owner"))
        if viewer_id:
            session.add(ProjectMember(project_id=project.id, user_id=uuid.UUID(viewer_id), role=role))
        content = empty_content(get_artifact_registry().get("prd"), "Restricted PRD")
        next(iter(content.sections.values())).blocks.append(
            TextBlock(text=f"{MARKER} body", citations=[Citation(label="S1", ref=str(uuid.uuid4()))])
        )
        artifact = Artifact(
            type="prd",
            title="Restricted PRD",
            project_id=project.id,
            owner_id=uuid.UUID(owner_id),
            current_version=2,
            classification=level,
        )
        session.add(artifact)
        await session.flush()
        for version in (1, 2):
            session.add(
                ArtifactVersion(
                    artifact_id=artifact.id,
                    version=version,
                    content=content.model_dump(mode="json"),
                    changed_sections=[],
                    author_type="nova",
                    summary="x",
                    state="current" if version == 2 else "superseded",
                )
            )
        return str(artifact.id)


async def test_viewer_without_clearance_gets_nothing_of_a_c3_artifact(app):
    _, owner_id = await _client(app, "owner")
    viewer, viewer_id = await _client(app, "viewer")
    aid = await _artifact(owner_id, viewer_id, level=3)
    base = f"/api/v1/artifacts/{aid}"

    assert aid not in {a["id"] for a in (await viewer.get("/api/v1/artifacts")).json()}
    assert "Restricted PRD" not in (await viewer.get("/api/v1/artifacts", params={"q": "Restricted"})).text
    assert (await viewer.get(base)).status_code == 404
    assert (await viewer.get(base, params={"version": 1})).status_code == 404
    for fmt in ("md", "json"):
        response = await viewer.get(f"{base}/export", params={"format": fmt})
        assert response.status_code == 404 and MARKER not in response.text
    assert (await viewer.get(f"{base}/versions")).status_code == 404
    assert (await viewer.get(f"{base}/compare", params={"from": 1, "to": 2})).status_code == 404
    assert (await viewer.get(f"{base}/comments")).status_code == 404
    assert (await viewer.get(f"{base}/provenance")).status_code == 404
    refused = await viewer.get(base)
    assert "Restricted" not in refused.text and MARKER not in refused.text  # no title / preview in the error
    # Nothing of it either in the activity feed or in the global search.
    assert "Restricted PRD" not in (await viewer.get("/api/v1/activity")).text
    assert "Restricted PRD" not in (await viewer.get("/api/v1/search", params={"q": "Restricted"})).text


async def test_the_same_rule_applies_to_the_owner_and_to_admins(app):
    owner, owner_id = await _client(app, "owner")
    aid = await _artifact(owner_id, None, level=3)
    assert (await owner.get(f"/api/v1/artifacts/{aid}")).status_code == 404  # default policy: C1
    assert aid not in {a["id"] for a in (await owner.get("/api/v1/artifacts")).json()}
    await _clearance(owner_id, 3)
    assert (await owner.get(f"/api/v1/artifacts/{aid}")).status_code == 200

    async with db.session_scope() as session:
        admin = await session.get(User, uuid.UUID(owner_id))
        admin.is_admin = True
    other_aid = await _artifact(owner_id, None, level=3)
    async with db.session_scope() as session:
        account = await session.get(OrbitAccount, uuid.UUID(owner_id))
        account.clearance = 1  # clearance lowered in ORBIT: effective at the next request
    assert (await owner.get(f"/api/v1/artifacts/{other_aid}")).status_code == 404  # admin is not exempt


async def test_clearance_is_a_ceiling_not_a_switch(app):
    _, owner_id = await _client(app, "owner")
    viewer, viewer_id = await _client(app, "viewer")
    c1 = await _artifact(owner_id, viewer_id, level=1)
    c2 = await _artifact(owner_id, viewer_id, level=2)
    c3 = await _artifact(owner_id, viewer_id, level=3)
    await _clearance(viewer_id, 2)
    assert (await viewer.get(f"/api/v1/artifacts/{c1}")).status_code == 200
    assert (await viewer.get(f"/api/v1/artifacts/{c2}")).status_code == 200
    assert (await viewer.get(f"/api/v1/artifacts/{c3}")).status_code == 404
    listed = {a["id"] for a in (await viewer.get("/api/v1/artifacts")).json()}
    assert {c1, c2} <= listed and c3 not in listed


async def test_an_editor_below_the_clearance_cannot_edit_or_regenerate_a_c3_artifact(app):
    _, owner_id = await _client(app, "owner")
    editor, editor_id = await _client(app, "editor")
    aid = await _artifact(owner_id, editor_id, level=3, role="editor")
    base = f"/api/v1/artifacts/{aid}"
    assert (await editor.post(f"{base}/sections/summary/regenerate", json={"instruction": "rewrite"})).status_code == 404
    assert (await editor.patch(base, json={"base_version": 2, "status": "final"})).status_code == 404
    assert (await editor.post(f"{base}/refresh")).status_code == 404
    async with db.session_scope() as session:
        assert await session.scalar(select(Task.id).where(Task.user_id == uuid.UUID(editor_id))) is None  # no run started


async def test_agent_tools_and_store_obey_the_clearance_of_the_run(app):
    _, owner_id = await _client(app, "owner")
    _, editor_id = await _client(app, "editor")
    aid = await _artifact(owner_id, editor_id, level=3, role="editor")
    async with db.session_scope() as session:
        low = principal_for(await session.get(User, uuid.UUID(editor_id)))
    store = SqlExecutionStore(low)
    assert await store.get_artifact(aid, editor_id) is None
    assert await store.list_artifact_outlines(editor_id, project_id=None) == []
    async with db.session_scope() as session:
        try:
            await require_artifact(session, aid, low)
        except AccessDenied:
            pass
        else:
            raise AssertionError("C1 principal must not reach a C3 artifact")
    snapshot = await SqlExecutionStore(replace(low, clearance=3)).get_artifact(aid, editor_id)
    assert snapshot is not None and snapshot.classification == 3  # the same run, with the right clearance, sees it


async def test_replay_with_original_context_is_refused_after_a_clearance_drop(app):
    owner, owner_id = await _client(app, "owner")
    async with db.session_scope() as session:
        item = ContextItem(
            citation="S1", ref_id="r1", kind="document", title="Synthetic C3 doc", excerpt=MARKER, classification=3
        )
        task = Task(user_id=uuid.UUID(owner_id), objective="x", origin="chat", autonomy="assist", input={}, status="completed")
        session.add(task)
        await session.flush()
        session.add(
            ContextRetrievalReference(
                user_id=uuid.UUID(owner_id),
                task_id=task.id,
                project_slug="p",
                max_classification=3,
                items=[item.model_dump(mode="json")],
            )
        )
        tid = str(task.id)
    response = await owner.post(f"/api/v1/executions/{tid}/replay", json={"context": "original"})
    assert response.status_code == 422 and response.json()["code"] == "clearance"
    assert MARKER not in response.text
    # A replay with live context re-queries ORBIT with the current rights: not affected by the stored extracts.
    assert (await owner.post(f"/api/v1/executions/{tid}/replay", json={"context": "none"})).status_code == 202


async def test_pinned_context_above_the_current_clearance_is_never_reinjected(app):
    _, owner_id = await _client(app, "owner")
    async with db.session_scope() as session:
        low = ContextItem(citation="S1", ref_id="r1", kind="document", title="Internal", excerpt="ok", classification=1)
        high = ContextItem(citation="S2", ref_id="r2", kind="document", title="Synthetic C3", excerpt=MARKER, classification=3)
        ref = ContextRetrievalReference(
            user_id=uuid.UUID(owner_id),
            project_slug="p",
            max_classification=3,
            items=[low.model_dump(mode="json"), high.model_dump(mode="json")],
        )
        session.add(ref)
        await session.flush()
        principal = principal_for(await session.get(User, uuid.UUID(owner_id)))
        ref_id = str(ref.id)
    served = await SqlExecutionStore(principal).get_context_references([ref_id], owner_id)
    assert [i.ref_id for r in served for i in r.items] == ["r1"]
