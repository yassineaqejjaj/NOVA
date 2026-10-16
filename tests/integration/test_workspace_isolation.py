"""Workspace isolation (ADR 001 §9, NOV-107): two workspaces, synthetic data, ``off`` / ``shadow`` / ``enforce``.

A and B each have users and an Artifact. In ``enforce`` nothing of A is visible, writable or referable from B (a platform
administrator of B included), a foreign object answers exactly like an unknown one (404), and everything a run creates
carries its own workspace. In ``shadow`` nothing is refused, but what ``enforce`` would hide is counted. In ``off`` nothing
changes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import select

from nova.agent.runtime import open_checkpointer
from nova.config import get_settings
from nova.domain.context import ContextItem
from nova.domain.outputs import IntentClassification
from nova.domain.workspace import outbox_key, thread_id
from nova.infra import db, scope
from nova.infra.db import Base
from nova.infra.models import (
    Artifact,
    ContextRetrievalReference,
    ExecutionEvent,
    ForgetRequest,
    Project,
    ProjectMember,
    ProjectReference,
    Task,
    User,
    Workspace,
)
from nova.services import compositions, maintenance, workspaces
from nova.services.users import upsert_user
from nova_api.main import create_app

SECRET = "synthetic-webhook-secret-0123456789abcdef"
A, B = uuid.uuid4(), uuid.uuid4()
SLUG = "alpha"


@pytest_asyncio.fixture
async def app(monkeypatch):
    monkeypatch.setattr(get_settings(), "orbit_webhook_secret", SECRET)
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
def enforce(monkeypatch):
    monkeypatch.setattr(get_settings(), "workspace_enforcement", "enforce")
    scope.reset_shadow_counts()


@pytest.fixture
def shadow(monkeypatch):
    monkeypatch.setattr(get_settings(), "workspace_enforcement", "shadow")
    scope.reset_shadow_counts()


async def _member(app, workspace: uuid.UUID, name: str, *, admin: bool = False) -> httpx.AsyncClient:
    """A signed-in user of ``workspace`` (its account is created there, as a validated token would)."""
    email = f"{name}-{uuid.uuid4().hex[:6]}@example.com"
    async with db.session_scope() as session:
        await upsert_user(
            session,
            subject=f"dev:{email}",
            email=email,
            display_name=name,
            realm_roles=["nova-user"],
            is_admin=False,
            workspace_id=workspace,
        )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    login = await client.post("/api/v1/auth/dev-login", json={"email": email, "name": name, "title": "QA"})
    assert login.status_code == 200, login.text
    if admin:
        async with db.session_scope() as session:
            user = await session.scalar(select(User).where(User.email == email))
            user.is_admin = True
            user.realm_roles = ["nova-admin"]
        # dev sign-in resets the flag on each login; the cookie of this client is the session
    return client


async def _me(client: httpx.AsyncClient) -> str:
    return (await client.get("/api/v1/me")).json()["id"]


async def _artifact(client: httpx.AsyncClient, title: str) -> str:
    response = await client.post("/api/v1/artifacts", json={"type": "prd", "title": title})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _run(client: httpx.AsyncClient, llm, text: str = "Create a PRD for CSV exports") -> str:
    llm.intent = lambda m: IntentClassification(
        kind="run_workflow", goal="PRD", candidate_skill_ids=["prd"], context_query="scheduled CSV exports"
    )
    conversation = (await client.post("/api/v1/conversations", json={})).json()
    response = await client.post(f"/api/v1/conversations/{conversation['id']}/messages", json={"text": text})
    assert response.status_code == 202, response.text
    return response.json()["task"]["id"]


def _same_as_unknown(foreign: httpx.Response, unknown: httpx.Response) -> None:
    """A foreign object answers exactly as an identifier nobody ever had (ADR §9, invariant 3)."""
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json()


# --- enforce: reads, lists, search, export, replay ---------------------------------------------------------------------------


async def test_a_foreign_artifact_is_a_404_for_everyone_even_a_platform_admin(app, enforce):
    alice = await _member(app, A, "alice")
    bob = await _member(app, B, "bob")
    admin_b = await _member(app, B, "root", admin=True)
    artifact = await _artifact(alice, "ALPHA-SECRET-ROADMAP")
    unknown = str(uuid.uuid4())

    assert (await alice.get(f"/api/v1/artifacts/{artifact}")).status_code == 200
    for who in (bob, admin_b):
        for path in ("", "/versions", "/comments", "/provenance", "/freshness", "/export?format=md", "/export?format=json"):
            _same_as_unknown(
                await who.get(f"/api/v1/artifacts/{artifact}{path}"), await who.get(f"/api/v1/artifacts/{unknown}{path}")
            )
        patch = {"base_version": 1, "title": "hijacked"}
        _same_as_unknown(
            await who.patch(f"/api/v1/artifacts/{artifact}", json=patch),
            await who.patch(f"/api/v1/artifacts/{unknown}", json=patch),
        )
        comment = {"section_key": "summary", "body": "hello"}
        _same_as_unknown(
            await who.post(f"/api/v1/artifacts/{artifact}/comments", json=comment),
            await who.post(f"/api/v1/artifacts/{unknown}/comments", json=comment),
        )
        assert artifact not in {a["id"] for a in (await who.get("/api/v1/artifacts")).json()}
        assert "ALPHA-SECRET" not in (await who.get("/api/v1/artifacts?q=ALPHA")).text
        assert "ALPHA-SECRET" not in (await who.get("/api/v1/search", params={"q": "ALPHA-SECRET"})).text
    assert (await alice.get(f"/api/v1/artifacts/{artifact}")).json()["title"] == "ALPHA-SECRET-ROADMAP"  # untouched
    assert artifact in {a["id"] for a in (await alice.get("/api/v1/artifacts")).json()}


async def test_a_foreign_task_cannot_be_read_followed_replayed_or_listed(app, enforce, llm, orbit, forge):
    alice = await _member(app, A, "alice")
    bob = await _member(app, B, "bob")
    admin_b = await _member(app, B, "root", admin=True)
    task = await _run(alice, llm)
    unknown = str(uuid.uuid4())
    assert (await alice.get(f"/api/v1/executions/{task}")).json()["status"] == "completed"

    for who in (bob, admin_b):
        for method, path in (
            ("get", "/api/v1/executions/{}"),
            ("get", "/api/v1/executions/{}/events"),
            ("get", "/api/v1/executions/{}/replays"),
            ("get", "/api/v1/tasks/{}"),
            ("post", "/api/v1/executions/{}/replay"),
            ("post", "/api/v1/executions/{}/retry"),
            ("post", "/api/v1/executions/{}/cancel"),
        ):
            body = {"json": {}} if method == "post" else {}
            foreign = await getattr(who, method)(path.format(task), **body)
            _same_as_unknown(foreign, await getattr(who, method)(path.format(unknown), **body))
        for tab in ("active", "completed", "failed", "scheduled"):
            assert task not in {t["id"] for t in (await who.get("/api/v1/tasks", params={"tab": tab})).json()}
        assert task not in (await who.get("/api/v1/activity")).text
    replay = await alice.post(f"/api/v1/executions/{task}/replay", json={})  # the owner's replay stays in the owner's workspace
    assert replay.status_code == 202, replay.text
    async with db.session_scope() as session:
        rows = (await session.scalars(select(Task).where(Task.id.in_([uuid.UUID(task), uuid.UUID(replay.json()["id"])])))).all()
    assert {r.workspace_id for r in rows} == {A}


async def test_everything_a_run_creates_carries_its_workspace_and_its_own_checkpoint_thread(app, enforce, llm, orbit, forge):
    bob = await _member(app, B, "bob")
    task = await _run(bob, llm)
    assert (await bob.get(f"/api/v1/executions/{task}")).json()["status"] == "completed"
    await bob.post("/api/v1/feedback", json={"task_id": task, "rating": "useful"})

    async with db.platform_session_scope() as session:
        mine = await session.scalar(select(Task).where(Task.id == uuid.UUID(task)))
        assert mine.workspace_id == B
        checked = []
        for table in Base.metadata.sorted_tables:  # every row that points at this task, in every table, is in B
            if "workspace_id" not in table.c or "task_id" not in table.c:
                continue
            wanted = mine.id if isinstance(table.c.task_id.type, sa.Uuid) else str(mine.id)
            rows = (await session.execute(sa.select(table.c.workspace_id).where(table.c.task_id == wanted))).all()
            assert {r[0] for r in rows} <= {B}, table.name
            if rows:
                checked.append(table.name)
        assert {"artifacts", "execution_events", "skill_executions", "llm_calls", "task_steps", "feedback"} <= set(checked), (
            checked
        )
    async with open_checkpointer(get_settings().database_url) as saver:
        namespaced = await saver.aget_tuple({"configurable": {"thread_id": thread_id(task, B)}})
        bare = await saver.aget_tuple({"configurable": {"thread_id": task}})
    assert namespaced is not None and bare is None  # the checkpoint thread carries the workspace


async def test_a_run_of_the_default_workspace_keeps_its_historical_keys(app, enforce, llm, orbit, forge):
    default = get_settings().default_workspace_id
    assert thread_id("t-1", default) == "t-1" and outbox_key("t-1", default) == "nova-task:t-1"
    assert thread_id("t-1", None) == "t-1" and outbox_key("t-1", None) == "nova-task:t-1"
    assert thread_id("t-1", A) != thread_id("t-1", B) != "t-1" and outbox_key("t-1", A) != outbox_key("t-1", B)
    assert len(thread_id(uuid.uuid4(), A)) <= 64  # WorkflowExecution.thread_id is a VARCHAR(64)


async def test_projects_users_and_conversations_are_invisible_across_workspaces(app, enforce):
    alice = await _member(app, A, "alice")
    bob = await _member(app, B, "bob")
    project = (await alice.post("/api/v1/projects", json={"name": "ALPHA-ONLY", "description": "x"})).json()["id"]
    conversation = (await alice.post("/api/v1/conversations", json={})).json()["id"]
    unknown = str(uuid.uuid4())

    _same_as_unknown(await bob.get(f"/api/v1/projects/{project}"), await bob.get(f"/api/v1/projects/{unknown}"))
    _same_as_unknown(await bob.get(f"/api/v1/conversations/{conversation}"), await bob.get(f"/api/v1/conversations/{unknown}"))
    assert "ALPHA-ONLY" not in (await bob.get("/api/v1/projects")).text
    assert "alice" not in (await bob.get("/api/v1/team")).text
    # a message that names a project of another workspace is refused like an unknown project
    mine = (await bob.post("/api/v1/conversations", json={})).json()["id"]
    foreign = await bob.post(f"/api/v1/conversations/{mine}/messages", json={"text": "hi", "project_id": project})
    unknown_project = await bob.post(f"/api/v1/conversations/{mine}/messages", json={"text": "hi", "project_id": unknown})
    assert foreign.status_code == unknown_project.status_code and foreign.status_code >= 400


# --- enforce: writes and references across workspaces -------------------------------------------------------------------------


async def test_a_write_or_a_reference_across_workspaces_is_refused_and_a_workspace_never_changes(enforce):
    async with db.session_scope() as session:
        a_user = await upsert_user(
            session, subject=f"x-{uuid.uuid4()}", email="a@x.io", display_name="a", realm_roles=[], is_admin=False, workspace_id=A
        )
        b_user = await upsert_user(
            session, subject=f"x-{uuid.uuid4()}", email="b@x.io", display_name="b", realm_roles=[], is_admin=False, workspace_id=B
        )
        project = Project(slug=f"p-{uuid.uuid4().hex[:6]}", name="A's", created_by=a_user.id)
        session.add(project)
        await session.flush()
        assert project.workspace_id == A  # from its creator
        a_id, b_id, project_id = a_user.id, b_user.id, project.id
    with pytest.raises(scope.WorkspaceViolation):  # a task of B's user on A's project
        async with db.session_scope() as session:
            session.add(Task(user_id=b_id, project_id=project_id, objective="x", input={}))
    with pytest.raises(scope.WorkspaceViolation):  # a row created in another workspace than the scope's
        async with db.session_scope() as session:
            with scope.workspace_scope(B):
                session.add(Task(user_id=a_id, objective="x", input={}))
                await session.flush()
    with pytest.raises(scope.WorkspaceViolation):  # the workspace of a row never changes
        async with db.session_scope() as session:
            (await session.get(Project, project_id)).workspace_id = B


async def test_a_token_of_another_workspace_does_not_open_an_account(app, enforce, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    subject = f"sub-{uuid.uuid4()}"

    def validate(token, _settings, **_):
        return {"sub": subject, "email": "carol@example.com", "name": "Carol", "orion_workspace_id": token}

    monkeypatch.setattr("nova_api.auth.validate_oidc_token", validate)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {A}"})
        assert first.status_code == 200
        again = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {A}"})
        assert again.status_code == 200
        other = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {B}"})
        assert other.status_code == 401 and other.json()["code"] == "unauthorized"
        junk = await client.get(
            "/api/v1/me", headers={"Authorization": "Bearer not-a-uuid"}
        )  # no usable claim: the account's own
        assert junk.status_code == 200
    async with db.session_scope() as session:
        user = await session.scalar(select(User).where(User.subject == subject))
        assert user.workspace_id == A  # created in the workspace the token named; never moved
        assert await session.get(Workspace, A) is not None  # and the workspace is registered


# --- enforce: ORBIT webhook, forgetting, retention, caches ---------------------------------------------------------------------


def _signed(payload: dict) -> tuple[bytes, dict]:
    body = json.dumps(payload, sort_keys=True).encode()
    return body, {
        "Content-Type": "application/json",
        "X-Orbit-Delivery": payload["id"],
        "X-Orbit-Signature": "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest(),
    }


async def _reference(workspace: uuid.UUID, slug: str, document: str) -> tuple[uuid.UUID, uuid.UUID]:
    """A task, and the extract ORBIT served to it, in ``workspace``."""
    async with db.session_scope() as session:
        user = await upsert_user(
            session,
            subject=f"u-{uuid.uuid4()}",
            email=f"{uuid.uuid4().hex[:6]}@x.io",
            display_name="u",
            realm_roles=[],
            is_admin=False,
            workspace_id=workspace,
        )
        task = Task(user_id=user.id, objective="x", origin="chat", autonomy="assist", input={}, status="completed")
        session.add(task)
        await session.flush()
        item = ContextItem(
            citation="S1", ref_id="c1", kind="document", title="t", excerpt="EXCERPT", classification=1, document_id=document
        )
        ref = ContextRetrievalReference(
            user_id=user.id, task_id=task.id, project_slug=slug, max_classification=1, items=[item.model_dump(mode="json")]
        )
        session.add(ref)
        await session.flush()
        return ref.id, task.id


async def _project_linked_to_orbit(workspace: uuid.UUID, slug: str) -> None:
    async with db.session_scope() as session:
        owner = await upsert_user(
            session,
            subject=f"o-{uuid.uuid4()}",
            email=f"{uuid.uuid4().hex[:6]}@x.io",
            display_name="o",
            realm_roles=[],
            is_admin=False,
            workspace_id=workspace,
        )
        project = Project(slug=f"{slug}-{uuid.uuid4().hex[:6]}", name="p", created_by=owner.id)
        session.add(project)
        await session.flush()
        session.add(ProjectReference(project_id=project.id, system="orbit", external_id=slug))
        assert project.workspace_id == workspace


async def _revoked(ref_id: uuid.UUID) -> bool:
    async with db.platform_session_scope() as session:
        return (await session.get(ContextRetrievalReference, ref_id)).revoked_at is not None


async def _post_event(app, payload: dict) -> httpx.Response:
    body, headers = _signed(payload)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as anonymous:
        return await anonymous.post("/api/v1/webhooks/orbit", content=body, headers=headers)


def _event(slug: str, document: str, **extra) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "type": "document.acl_changed",
        "project": {"id": str(uuid.uuid4()), "slug": slug},
        "target_type": "document",
        "target_id": document,
        "created_at": datetime.now(UTC).isoformat(),
        **extra,
    }


async def test_an_orbit_event_revokes_only_in_the_workspace_it_is_about(app, enforce):
    slug, document = f"shared-{uuid.uuid4().hex[:6]}", f"doc-{uuid.uuid4().hex[:8]}"
    in_a, _ = await _reference(A, slug, document)
    in_b, _ = await _reference(B, slug, document)  # same ORBIT project slug and document id, other workspace
    response = await _post_event(app, _event(slug, document, orion_workspace_id=str(A)))  # the signed payload says A
    assert response.status_code == 200 and response.json()["status"] == "processed"
    assert await _revoked(in_a) is True and await _revoked(in_b) is False


async def test_an_orbit_event_without_a_workspace_follows_the_projects_that_reference_the_slug(app, enforce):
    slug, document = f"known-{uuid.uuid4().hex[:6]}", f"doc-{uuid.uuid4().hex[:8]}"
    await _project_linked_to_orbit(B, slug)  # only B's NOVA projects point at this ORBIT project
    in_a, _ = await _reference(A, slug, document)
    in_b, _ = await _reference(B, slug, document)
    assert (await _post_event(app, _event(slug, document))).status_code == 200
    assert await _revoked(in_b) is True and await _revoked(in_a) is False
    async with db.platform_session_scope() as session:
        from nova.infra.models import OrbitEvent

        row = await session.scalar(select(OrbitEvent).order_by(OrbitEvent.received_at.desc()).limit(1))
        assert row.workspace_id == B


async def test_an_orbit_event_for_a_slug_known_in_two_workspaces_applies_to_both(app, enforce):
    slug, document = f"both-{uuid.uuid4().hex[:6]}", f"doc-{uuid.uuid4().hex[:8]}"
    await _project_linked_to_orbit(A, slug)
    await _project_linked_to_orbit(B, slug)
    in_a, _ = await _reference(A, slug, document)
    in_b, _ = await _reference(B, slug, document)
    assert (await _post_event(app, _event(slug, document))).status_code == 200  # revoking too much is safe, too little is not
    assert await _revoked(in_a) is True and await _revoked(in_b) is True


async def test_forgetting_and_retention_operate_per_workspace(enforce):
    from nova.services import forget

    slug = f"erase-{uuid.uuid4().hex[:6]}"
    in_a, task_a = await _reference(A, slug, "doc-a")
    in_b, task_b = await _reference(B, slug, "doc-b")
    async with db.session_scope() as session:
        with scope.workspace_scope(A):  # an administrator of A forgets the project
            effects = await forget.forget_project(session, project_slug=slug, actor_id=None)
    assert effects["references"] == 1
    async with db.platform_session_scope() as session:
        assert await session.get(ContextRetrievalReference, in_a) is None
        assert await session.get(ContextRetrievalReference, in_b) is not None  # B's copy of "the same" project stays
        request = (await session.scalars(select(ForgetRequest).order_by(ForgetRequest.created_at.desc()).limit(1))).one()
        assert request.workspace_id == A

    # retention: an old event in each workspace; the run for A deletes A's only, the full run deletes both
    old = datetime.now(UTC) - timedelta(days=get_settings().execution_event_retention_days + 5)
    async with db.session_scope() as session:
        session.add_all(
            [
                ExecutionEvent(task_id=task_a, seq=900, type="x", payload={}, created_at=old, workspace_id=A),
                ExecutionEvent(task_id=task_b, seq=900, type="x", payload={}, created_at=old, workspace_id=B),
            ]
        )
    with scope.workspace_scope(A):
        assert (await maintenance._retain())["execution_events"] >= 1
    async with db.platform_session_scope() as session:
        left = {e.workspace_id for e in (await session.scalars(select(ExecutionEvent).where(ExecutionEvent.seq == 900))).all()}
    assert left == {B}
    assert (await maintenance.apply_retention())["execution_events"] >= 1  # enforce: workspace by workspace, nothing is skipped
    async with db.platform_session_scope() as session:
        assert (await session.scalars(select(ExecutionEvent).where(ExecutionEvent.seq == 900))).all() == []


async def test_caches_are_keyed_by_workspace(enforce):
    with scope.workspace_scope(A):
        key_a = workspaces.cache_key("prd")
    with scope.workspace_scope(B):
        key_b = workspaces.cache_key("prd")
    assert key_a != key_b and key_a == (A, "prd")
    compositions._cache[key_a] = (10**12, {"skill": 1.0})
    with scope.workspace_scope(B):
        async with db.session_scope() as session:
            assert "skill" not in await compositions.priors(session, "prd")  # B never reads what A's history produced
    compositions.invalidate()


async def test_platform_records_are_visible_from_every_workspace(enforce):
    from nova.integrations.forge.versions import cached_version_id, remember_version

    key = f"k-{uuid.uuid4().hex[:6]}"
    with scope.workspace_scope(A):
        await remember_version("release", key, "link-1", "ver-1", {})
    with scope.workspace_scope(B):
        assert await cached_version_id("release", key, "link-1") == "ver-1"  # FORGE's versions are platform records


# --- shadow: counts, never refuses ---------------------------------------------------------------------------------------------


async def test_shadow_counts_what_enforce_would_hide_and_refuses_nothing(app, shadow):
    alice = await _member(app, A, "alice")
    admin_b = await _member(app, B, "root", admin=True)
    artifact = await _artifact(alice, "ALPHA-SHADOW")
    scope.reset_shadow_counts()
    response = await admin_b.get(f"/api/v1/artifacts/{artifact}")  # an administrator reads across: allowed, but counted
    assert response.status_code == 200 and response.json()["title"] == "ALPHA-SHADOW"
    counts = scope.shadow_counts()
    assert counts.get("read:artifacts", 0) >= 1, counts
    assert (await alice.get(f"/api/v1/artifacts/{artifact}")).status_code == 200
    own = scope.shadow_counts().get("read:artifacts", 0)
    assert (await alice.get(f"/api/v1/artifacts/{artifact}")).status_code == 200
    assert scope.shadow_counts().get("read:artifacts", 0) == own  # reading one's own workspace counts nothing


async def test_shadow_counts_a_write_across_workspaces_and_lets_it_through(shadow):
    scope.reset_shadow_counts()
    async with db.session_scope() as session:
        user = await upsert_user(
            session, subject=f"x-{uuid.uuid4()}", email="s@x.io", display_name="s", realm_roles=[], is_admin=False, workspace_id=A
        )
        with scope.workspace_scope(B):
            session.add(Task(user_id=user.id, objective="x", input={}))
            await session.flush()
    assert scope.shadow_counts().get("write:tasks") == 1


# --- off: nothing changes -----------------------------------------------------------------------------------------------------------


async def test_off_does_not_filter_count_or_read_claims(app, monkeypatch, llm, orbit, forge):
    assert get_settings().workspace_enforcement == "off"
    scope.reset_shadow_counts()
    alice = await _member(app, A, "alice")  # `off`: the account is created in the default workspace, whatever it is told
    admin = await _member(app, B, "root", admin=True)
    artifact = await _artifact(alice, "ALPHA-OFF")
    assert (await admin.get(f"/api/v1/artifacts/{artifact}")).status_code == 200  # an administrator still reads everything
    task = await _run(alice, llm)
    assert (await admin.get(f"/api/v1/executions/{task}")).status_code == 200
    assert scope.shadow_counts() == {}
    async with db.session_scope() as session:
        assert (await session.get(Artifact, uuid.UUID(artifact))).workspace_id == get_settings().default_workspace_id
        assert (await session.get(Task, uuid.UUID(task))).workspace_id == get_settings().default_workspace_id
        assert scope.current_workspace() is None


# --- the default workspace and the ORION project id ---------------------------------------------------------------------------------


async def test_the_default_workspace_is_registered_and_projects_get_an_orion_id(app):
    async with db.session_scope() as session:
        assert await session.get(Workspace, get_settings().default_workspace_id) is not None
        first = Project(slug=f"o-{uuid.uuid4().hex[:6]}", name="one")
        second = Project(slug=f"o-{uuid.uuid4().hex[:6]}", name="two")
        reference = ProjectReference(project=first, system="orbit", external_id="forge")
        session.add_all([first, second, reference])
        await session.flush()
        assert first.orion_project_id and first.orion_project_id != second.orion_project_id

        orbit_says = uuid.uuid4()
        assert await workspaces.align_orion_project_id(session, first, reference, orbit_says) is True
        assert first.orion_project_id == orbit_says and reference.orion_project_id == orbit_says
        assert await workspaces.align_orion_project_id(session, first, reference, orbit_says) is False  # idempotent
        with pytest.raises(ValueError):  # an id never changes once ORBIT reported it
            await workspaces.align_orion_project_id(session, first, reference, uuid.uuid4())
        other = ProjectReference(project=second, system="orbit", external_id="other")
        session.add(other)
        await session.flush()
        with pytest.raises(ValueError):  # and belongs to one project only
            await workspaces.align_orion_project_id(session, second, other, orbit_says)
        session.add(
            ProjectMember(
                project_id=first.id,
                user_id=(
                    await upsert_user(
                        session, subject=f"m-{uuid.uuid4()}", email="m@x.io", display_name="m", realm_roles=[], is_admin=False
                    )
                ).id,
                role="owner",
            )
        )
        await session.flush()


# --- rows created outside any request (workers) inherit the workspace of what they are about -------------------------------------


async def test_rows_created_by_a_worker_take_the_workspace_of_the_run_they_are_about(shadow):
    from nova.domain.evaluation import ExecutionRecord  # noqa: F401 - the outbox stores one
    from nova.infra.models import AuditEvent, ForgeErasureRequest, IntegrationReference
    from nova.services import forge_outbox

    _, task_id = await _reference(B, f"w-{uuid.uuid4().hex[:6]}", "doc-w")  # a task of workspace B
    async with db.session_scope() as session:  # no scope at all, as in a Celery job
        assert scope.current_workspace() is None
        owner = await session.scalar(select(Task.user_id).where(Task.id == task_id))
        session.add_all(
            [
                AuditEvent(actor_id=owner, action="x", target_type="task", target_id=str(task_id)),
                IntegrationReference(system="forge", kind="evaluation", nova_type="task", nova_id=str(task_id), external_id="r1"),
                ForgeErasureRequest(run_id=f"run-{uuid.uuid4().hex}", task_id=task_id),
            ]
        )
    async with db.platform_session_scope() as session:
        for model, column, value in (
            (AuditEvent, AuditEvent.target_id, str(task_id)),
            (IntegrationReference, IntegrationReference.nova_id, str(task_id)),
            (ForgeErasureRequest, ForgeErasureRequest.task_id, task_id),
        ):
            row = await session.scalar(select(model).where(column == value))
            assert row.workspace_id == B, model.__name__
    assert forge_outbox.key_of(str(task_id), B) == f"nova-task:{B.hex[:16]}:{task_id}"
