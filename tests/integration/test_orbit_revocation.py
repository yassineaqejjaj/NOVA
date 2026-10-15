"""ORBIT revocation events (NOV-80 contract): signed webhook, revoked extracts, derived Artifacts to review (NOV-81).

Events are synthetic and signed in the test with ``X-Orbit-Signature: sha256=<hmac>``; no ORBIT is involved.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest_asyncio
from sqlalchemy import select

from nova.artifacts.registry import get_artifact_registry
from nova.config import get_settings
from nova.domain.artifacts import Citation, TextBlock, empty_content
from nova.domain.context import ContextError, ContextItem, ContextQuery
from nova.infra import db
from nova.infra.crypto import encrypt
from nova.infra.models import (
    Artifact,
    ArtifactVersion,
    AuditEvent,
    ContextRetrievalReference,
    OrbitAccount,
    OrbitEvent,
    Project,
    ProjectMember,
    Task,
    User,
)
from nova.integrations.orbit.adapter import OrbitContextProvider
from nova_api.main import create_app

SECRET = "synthetic-webhook-secret-0123456789abcdef"
SLUG = "forge"


@pytest_asyncio.fixture
async def app(monkeypatch):
    monkeypatch.setattr(get_settings(), "orbit_webhook_secret", SECRET)
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


async def _client(app, name: str = "owner") -> tuple[httpx.AsyncClient, str]:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    login = await client.post(
        "/api/v1/auth/dev-login", json={"email": f"{name}-{uuid.uuid4().hex[:6]}@example.com", "name": name, "title": "QA"}
    )
    assert login.status_code == 200, login.text
    return client, (await client.get("/api/v1/me")).json()["id"]


def _event(type_: str, target_type: str, target_id: str, *, delivery: str | None = None, **extra) -> tuple[bytes, dict]:
    """A NOV-80 payload and its signed headers."""
    payload = {
        "id": delivery or str(uuid.uuid4()),
        "type": type_,
        "project": {"id": str(uuid.uuid4()), "slug": SLUG},
        "target_type": target_type,
        "target_id": target_id,
        "created_at": datetime.now(UTC).isoformat(),
        "restricted": True,
        "title": "Restricted",
        "summary": "",
        "effective_at": datetime.now(UTC).isoformat(),
        "old_classification": None,
        "new_classification": None,
        **extra,
    }
    body = json.dumps(payload, sort_keys=True).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Orbit-Event": type_,
        "X-Orbit-Delivery": payload["id"],
        "X-Orbit-Signature": "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest(),
    }
    return body, headers


async def _send(app, type_: str, target_type: str, target_id: str, **kwargs) -> httpx.Response:
    body, headers = _event(type_, target_type, target_id, **kwargs)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as anonymous:
        return await anonymous.post("/api/v1/webhooks/orbit", content=body, headers=headers)


async def _derived(owner_id: str, *, document_id: str | None = "auto", memory_id: str | None = None) -> dict[str, str]:
    """A completed task, the extract ORBIT served to it, and an Artifact citing that extract (synthetic)."""
    document_id = f"doc-{uuid.uuid4().hex[:8]}" if document_id == "auto" else document_id
    memory_id = f"mem-{uuid.uuid4().hex[:8]}" if memory_id == "auto" else memory_id
    async with db.session_scope() as session:
        task = Task(user_id=uuid.UUID(owner_id), objective="x", origin="chat", autonomy="assist", input={}, status="completed")
        project = Project(slug=f"p-{uuid.uuid4().hex[:6]}", name="Synthetic")
        session.add_all([task, project])
        await session.flush()
        session.add(ProjectMember(project_id=project.id, user_id=uuid.UUID(owner_id), role="owner"))
        item = ContextItem(
            citation="S1",
            ref_id="chunk-1",
            kind="memory" if memory_id else "document",
            title="Synthetic source",
            excerpt="SYNTHETIC-EXCERPT",
            classification=1,
            document_id=document_id,
            memory_item_id=memory_id,
        )
        ref = ContextRetrievalReference(
            user_id=uuid.UUID(owner_id),
            task_id=task.id,
            project_slug=SLUG,
            max_classification=1,
            items=[item.model_dump(mode="json")],
        )
        session.add(ref)
        await session.flush()
        content = empty_content(get_artifact_registry().get("prd"), "Derived PRD")
        next(iter(content.sections.values())).blocks.append(
            TextBlock(text="Derived body", citations=[Citation(label="S1", ref=str(ref.id))])
        )
        artifact = Artifact(
            type="prd",
            title="Derived PRD",
            project_id=project.id,
            owner_id=uuid.UUID(owner_id),
            current_version=1,
            classification=1,
        )
        session.add(artifact)
        await session.flush()
        session.add(
            ArtifactVersion(
                artifact_id=artifact.id,
                version=1,
                content=content.model_dump(mode="json"),
                changed_sections=[],
                author_type="nova",
                summary="x",
                state="current",
            )
        )
        return {
            "task": str(task.id),
            "ref": str(ref.id),
            "artifact": str(artifact.id),
            "doc": document_id or "",
            "mem": memory_id or "",
        }


async def _ref(ref_id: str) -> ContextRetrievalReference:
    async with db.session_scope() as session:
        return await session.get(ContextRetrievalReference, uuid.UUID(ref_id))


async def _artifact(artifact_id: str) -> Artifact:
    async with db.session_scope() as session:
        return await session.get(Artifact, uuid.UUID(artifact_id))


async def _audits(action: str) -> list[AuditEvent]:
    async with db.session_scope() as session:
        return list((await session.scalars(select(AuditEvent).where(AuditEvent.action == action))).all())


# --- Signature, idempotency, anti-replay -----------------------------------------------------------------------


async def test_a_bad_or_missing_signature_is_a_401_and_changes_nothing(app):
    _, owner = await _client(app)
    ids = await _derived(owner)
    body, headers = _event("document.forgotten", "document", ids["doc"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as anonymous:
        tampered = await anonymous.post("/api/v1/webhooks/orbit", content=body + b" ", headers=headers)
        unsigned = await anonymous.post(
            "/api/v1/webhooks/orbit", content=body, headers={k: v for k, v in headers.items() if k != "X-Orbit-Signature"}
        )
        wrong = await anonymous.post(
            "/api/v1/webhooks/orbit", content=body, headers={**headers, "X-Orbit-Signature": "sha256=" + "0" * 64}
        )
        garbage = await anonymous.post("/api/v1/webhooks/orbit", content=body, headers={**headers, "X-Orbit-Signature": "nope"})
    assert [r.status_code for r in (tampered, unsigned, wrong, garbage)] == [401, 401, 401, 401]
    assert (await _ref(ids["ref"])).revoked_at is None and (await _artifact(ids["artifact"])).review_requested_at is None


async def test_without_a_configured_secret_the_endpoint_refuses_everything(app, monkeypatch):
    monkeypatch.setattr(get_settings(), "orbit_webhook_secret", "")
    assert (await _send(app, "document.forgotten", "document", "doc-x")).status_code == 503


async def test_a_replayed_delivery_is_idempotent(app):
    _, owner = await _client(app)
    ids = await _derived(owner)
    delivery = str(uuid.uuid4())
    first = await _send(app, "document.forgotten", "document", ids["doc"], delivery=delivery)
    assert first.status_code == 200 and first.json()["status"] == "processed"
    revoked_at = (await _ref(ids["ref"])).revoked_at
    second = await _send(app, "document.forgotten", "document", ids["doc"], delivery=delivery)
    assert second.status_code == 200 and second.json()["status"] == "duplicate"
    assert (await _ref(ids["ref"])).revoked_at == revoked_at
    async with db.session_scope() as session:
        assert len((await session.scalars(select(OrbitEvent).where(OrbitEvent.delivery_id == delivery))).all()) == 1


async def test_a_stale_event_is_refused(app):
    old = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    response = await _send(app, "document.forgotten", "document", "doc-x", created_at=old)
    assert response.status_code == 400 and response.json()["code"] == "stale_event"


async def test_events_that_do_not_revoke_anything_are_acknowledged_and_ignored(app):
    response = await _send(app, "memory.created", "memory", "m-1")
    assert response.status_code == 200 and response.json()["status"] == "ignored"
    ping = await _send(app, "ping", "webhook", "x")
    assert ping.status_code == 200
    async with db.session_scope() as session:
        assert (await session.scalars(select(OrbitEvent).where(OrbitEvent.type == "memory.created"))).first() is None


# --- Effects ----------------------------------------------------------------------------------------------------


async def test_a_forgotten_document_revokes_the_extract_flags_the_artifact_and_blocks_replay(app):
    owner, owner_id = await _client(app)
    ids = await _derived(owner_id)
    other = await _derived(owner_id, document_id="auto")

    response = await _send(app, "document.forgotten", "document", ids["doc"])
    assert response.status_code == 200 and response.json()["effects"] == {"references": 1, "artifacts": 1}

    ref = await _ref(ids["ref"])
    assert ref.revoked_at is not None and ref.revoked_reason == "document.forgotten"
    assert (await _ref(other["ref"])).revoked_at is None  # another source is untouched
    artifact = await _artifact(ids["artifact"])
    assert artifact.review_requested_at is not None and artifact.review_reason == "document.forgotten"
    assert (await _artifact(other["artifact"])).review_requested_at is None
    assert [a.target_id for a in await _audits("orbit.revocation")][-1:] == [ids["doc"]]
    assert str(ids["artifact"]) in {a.target_id for a in await _audits("artifact.review_requested")}

    # replay with the original context: the revoked extract is never re-injected
    replay = await owner.post(f"/api/v1/executions/{ids['task']}/replay", json={"context": "original"})
    assert replay.status_code == 422 and replay.json()["code"] == "revoked"
    assert "SYNTHETIC-EXCERPT" not in replay.text


async def test_a_replay_keeps_the_extracts_that_were_not_revoked(app):
    owner, owner_id = await _client(app)
    ids = await _derived(owner_id)
    async with db.session_scope() as session:  # a second extract served to the same run
        session.add(
            ContextRetrievalReference(
                user_id=uuid.UUID(owner_id),
                task_id=uuid.UUID(ids["task"]),
                project_slug=SLUG,
                items=[
                    ContextItem(
                        citation="S1", ref_id="c2", kind="document", title="Kept", excerpt="kept", document_id="doc-kept"
                    ).model_dump(mode="json")
                ],
            )
        )
    await _send(app, "document.forgotten", "document", ids["doc"])
    replay = await owner.post(f"/api/v1/executions/{ids['task']}/replay", json={"context": "original"})
    assert replay.status_code == 202
    async with db.session_scope() as session:
        new = await session.get(Task, uuid.UUID(replay.json()["id"]))
    pinned = new.input["pinned_context_ref_ids"]
    assert len(pinned) == 1 and ids["ref"] not in pinned
    assert new.input["replay_overrides"]["revoked_sources"] == 1


async def test_acl_and_classification_changes_revoke_by_memory_or_document(app):
    _, owner = await _client(app)
    doc = await _derived(owner)
    mem = await _derived(owner, document_id=None, memory_id="auto")
    cls = await _derived(owner)
    assert (await _send(app, "document.acl_changed", "document", doc["doc"])).json()["effects"]["references"] == 1
    assert (await _send(app, "memory.acl_changed", "memory", mem["mem"])).json()["effects"]["references"] == 1
    changed = await _send(
        app, "document.classification_changed", "document", cls["doc"], old_classification=1, new_classification=3
    )
    assert changed.json()["effects"]["references"] == 1
    for ids, reason in ((doc, "document.acl_changed"), (mem, "memory.acl_changed"), (cls, "document.classification_changed")):
        assert (await _ref(ids["ref"])).revoked_reason == reason
        assert (await _artifact(ids["artifact"])).review_reason == reason


async def test_a_flagged_artifact_shows_a_banner_is_not_exportable_until_reviewed(app):
    owner, owner_id = await _client(app)
    ids = await _derived(owner_id)
    base = f"/api/v1/artifacts/{ids['artifact']}"
    assert (await owner.get(f"{base}/export")).status_code == 200
    await _send(app, "document.forgotten", "document", ids["doc"])

    shown = (await owner.get(base)).json()
    assert shown["review"]["pending"] is True and shown["review"]["reason"] == "document.forgotten"
    listed = next(a for a in (await owner.get("/api/v1/artifacts")).json() if a["id"] == ids["artifact"])
    assert listed["review"]["pending"]
    for fmt in ("md", "json"):
        refused = await owner.get(f"{base}/export", params={"format": fmt})
        assert refused.status_code == 409 and refused.json()["code"] == "needs_review"
    # the citation of the revoked extract is no longer resolvable
    assert (await owner.get(f"{base}/provenance")).json()["sources"] == []

    reviewed = await owner.post(f"{base}/review")
    assert reviewed.status_code == 200
    assert (await owner.get(base)).json()["review"]["pending"] is False
    assert (await owner.get(f"{base}/export")).status_code == 200
    assert str(ids["artifact"]) in {a.target_id for a in await _audits("artifact.reviewed")}


async def test_only_an_editor_can_mark_an_artifact_as_reviewed(app):
    _, owner_id = await _client(app)
    viewer, viewer_id = await _client(app, "viewer")
    ids = await _derived(owner_id)
    async with db.session_scope() as session:
        project_id = (await session.get(Artifact, uuid.UUID(ids["artifact"]))).project_id
        session.add(ProjectMember(project_id=project_id, user_id=uuid.UUID(viewer_id), role="viewer"))
    await _send(app, "document.forgotten", "document", ids["doc"])
    assert (await viewer.post(f"/api/v1/artifacts/{ids['artifact']}/review")).status_code == 404
    assert (await _artifact(ids["artifact"])).review_requested_at is not None


async def test_a_removed_member_loses_the_orbit_session_and_the_clearance(app):
    owner, owner_id = await _client(app)
    ids = await _derived(owner_id)
    orbit_id = f"orbit-{uuid.uuid4().hex[:8]}"
    async with db.session_scope() as session:
        session.add(
            OrbitAccount(
                user_id=uuid.UUID(owner_id),
                orbit_user_id=orbit_id,
                orbit_email="o@example.com",
                clearance=3,
                token_ciphertext=encrypt("synthetic-session-token"),
                expires_at=datetime.now(UTC) + timedelta(hours=5),
            )
        )
    assert (await owner.get("/api/v1/me/links")).json()["orbit"]["status"] == "ok"

    response = await _send(app, "member.removed", "user", orbit_id)
    assert response.status_code == 200 and response.json()["effects"]["sessions"] == 1

    async with db.session_scope() as session:
        account = await session.get(OrbitAccount, uuid.UUID(owner_id))
        assert account.token_ciphertext is None and account.revoked_at is not None and account.clearance == 1
    links = (await owner.get("/api/v1/me/links")).json()["orbit"]
    assert links["status"] == "revoked" and links["revoked_reason"] == "member.removed"
    assert (await _ref(ids["ref"])).revoked_reason == "member.removed"  # what that user was served in that project
    assert (await _artifact(ids["artifact"])).review_reason == "member.removed"
    provider = OrbitContextProvider(get_settings())
    try:
        await provider.overview(owner_id, SLUG)
    except ContextError as exc:
        assert exc.code == "unauthorized" and "revoked" in exc.message
    else:
        raise AssertionError("a revoked access must not reach ORBIT")


async def test_a_revoked_agent_key_stops_being_used_until_it_is_replaced(app, monkeypatch):
    _, owner_id = await _client(app)
    settings = get_settings()
    monkeypatch.setattr(settings, "orbit_agent_keys", f"{SLUG}:orb_synthetic_aaaaaaaaaaaaaaaaaaaa")
    provider = OrbitContextProvider(settings)

    response = await _send(app, "agent.revoked", "agent", "key-1")
    assert response.status_code == 200 and response.json()["effects"]["agent_keys"] == 1
    try:
        await provider.retrieve(ContextQuery(user_id=owner_id, project_slug=SLUG, task="x"))
    except ContextError as exc:
        assert exc.code == "unauthorized" and "revoked" in exc.message
    else:
        raise AssertionError("a revoked key must not be used")
    status = await provider.agent_keys_status()  # what the links screen shows (ORBIT unreachable here)
    assert status[0]["project"] == SLUG and status[0]["reason"] == "revoked" and status[0]["valid"] is False

    monkeypatch.setattr(settings, "orbit_agent_keys", f"{SLUG}:orb_synthetic_bbbbbbbbbbbbbbbbbbbb")  # the key was rotated
    try:
        await provider.retrieve(ContextQuery(user_id=owner_id, project_slug=SLUG, task="x"))
    except ContextError as exc:
        assert "revoked" not in exc.message  # the new key is tried (ORBIT is not reachable in tests)


async def test_a_key_orbit_still_accepts_is_used_again(app, monkeypatch):
    """The revoked key was another one of the project: the health check proves the configured one still works."""

    class StillValid:
        async def agent_self(self, auth):
            return {"name": "project key", "project_slug": SLUG}

    settings = get_settings()
    monkeypatch.setattr(settings, "orbit_agent_keys", f"{SLUG}:orb_synthetic_cccccccccccccccccccc")
    provider = OrbitContextProvider(settings, client=StillValid())
    await _send(app, "agent.revoked", "agent", "key-2")
    assert await provider._key_revoked(SLUG, "orb_synthetic_cccccccccccccccccccc")
    states = await provider.agent_keys_status()
    assert states[0]["valid"] is True and states[0]["reason"] is None
    assert not await provider._key_revoked(SLUG, "orb_synthetic_cccccccccccccccccccc")
    assert await _audits("orbit.agent_key_restored")


# --- Admin replay -----------------------------------------------------------------------------------------------


async def test_an_administrator_can_replay_an_event(app):
    admin, admin_id = await _client(app, "admin")
    async with db.session_scope() as session:
        (await session.get(User, uuid.UUID(admin_id))).is_admin = True
    ids = await _derived(admin_id)
    delivery = str(uuid.uuid4())
    await _send(app, "document.forgotten", "document", ids["doc"], delivery=delivery)
    async with db.session_scope() as session:
        event = (await session.scalars(select(OrbitEvent).where(OrbitEvent.delivery_id == delivery))).one()
        (await session.get(ContextRetrievalReference, uuid.UUID(ids["ref"]))).revoked_at = None  # as if the effect was lost
        event_id = str(event.id)

    listed = (await admin.get("/api/v1/admin/orbit-events")).json()
    assert listed[0]["id"] == event_id and listed[0]["status"] == "processed" and "payload" not in listed[0]
    replayed = await admin.post(f"/api/v1/admin/orbit-events/{event_id}/replay")
    assert replayed.status_code == 200 and replayed.json()["effects"]["references"] == 1
    assert (await _ref(ids["ref"])).revoked_at is not None
    assert await _audits("orbit.revocation_replayed")

    member, _ = await _client(app, "member")
    assert (await member.post(f"/api/v1/admin/orbit-events/{event_id}/replay")).status_code == 403
    assert (await member.get("/api/v1/admin/orbit-events")).status_code == 403
