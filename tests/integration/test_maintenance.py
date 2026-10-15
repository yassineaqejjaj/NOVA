"""Forgetting and retention: a forget event leaves no readable copy of the context NOVA kept (NOV-98).

Synthetic fixtures only: the marker below stands for an ORBIT excerpt that must disappear everywhere.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import Text, cast, select

from nova.agent.runtime import AgentRuntime, open_checkpointer
from nova.config import get_settings
from nova.infra import db
from nova.infra.models import (
    Artifact,
    ArtifactVersion,
    ContextRetrievalReference,
    ExecutionEvent,
    ForgeErasureRequest,
    ForgetRequest,
    IntegrationReference,
    Message,
    MessageBlock,
    Task,
    ToolExecution,
    User,
)
from nova.integrations.forge.client import ForgeError
from nova.services import forget, maintenance, providers
from nova.services.conversations import ComposerInput, create_conversation, submit
from nova.services.executions import run_task
from nova.services.replay import ReplayError, ReplayOptions, create_replay
from nova.skills.registry import get_skill_registry
from tests.integration.test_orbit_revocation import _client as _http_client
from tests.integration.test_orbit_revocation import _send, app  # noqa: F401  (signed ORBIT events and the app fixture)
from tests.support.fakes import context_item

MARKER = "SYNTHETIC-FORGET-MARKER"
DOC = "00000000-0000-0000-0000-000000000001"  # the document id of ``context_item(1, ...)``


class FakeForge:
    """FORGE's side of an erasure request: records what it is asked, answers as configured."""

    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.error: ForgeError | None = None

    async def delete_run(self, run_id: str) -> None:
        if self.error:
            raise self.error
        self.deleted.append(run_id)


async def _run(user, project, orbit, *, title: str = "Synthetic forgettable doc") -> str:
    """A finished run whose context holds the marker, with its checkpoint, Artifact and FORGE evaluation."""
    orbit.items = [context_item(1, title, excerpt=MARKER)]
    async with db.session_scope() as session:
        conversation = await create_conversation(session, user, project_id=project, title=None)
        _, _, task = await submit(
            session,
            user,
            conversation,
            ComposerInput(text="Create a PRD for scheduled CSV exports in FORGE", project_id=project),
            {s.id for s in get_skill_registry().all()},
        )
        task_id = str(task.id)
    assert await run_task(task_id, "start") == "completed"
    async with db.session_scope() as session:
        if await session.scalar(select(IntegrationReference.id).where(IntegrationReference.nova_id == task_id)) is None:
            session.add(
                IntegrationReference(
                    system="forge", kind="evaluation", nova_type="task", nova_id=task_id, external_id=f"run-{task_id}", data={}
                )
            )
    return task_id


async def _checkpoint(task_id: str):
    async with open_checkpointer(get_settings().database_url) as saver:
        return await AgentRuntime(saver).current_state(task_id)


async def _copies(task_id: str) -> dict[str, int]:
    """How many stores of this run still hold the marker, readable."""
    tid = uuid.UUID(task_id)
    has = lambda column: cast(column, Text).contains(MARKER)  # noqa: E731
    async with db.session_scope() as session:
        message_ids = select(Message.id).where(Message.task_id == tid)
        counts = {
            "references": select(ContextRetrievalReference.id).where(
                ContextRetrievalReference.task_id == tid, has(ContextRetrievalReference.items)
            ),
            "blocks": select(MessageBlock.id).where(MessageBlock.message_id.in_(message_ids), has(MessageBlock.payload)),
            "events": select(ExecutionEvent.id).where(ExecutionEvent.task_id == tid, has(ExecutionEvent.payload)),
            "tools": select(ToolExecution.id).where(ToolExecution.task_id == tid, has(ToolExecution.output)),
            "input": select(Task.id).where(Task.id == tid, has(Task.input)),
        }
        found = {name: len((await session.scalars(query)).all()) for name, query in counts.items()}
    found["checkpoint"] = int(MARKER in str(await _checkpoint(task_id) or ""))
    return found


async def _artifact_of(task_id: str) -> Artifact | None:
    async with db.session_scope() as session:
        return await session.scalar(select(Artifact).where(Artifact.task_id == uuid.UUID(task_id)))


async def test_forgetting_a_source_leaves_no_readable_copy_even_in_the_checkpoint(user, project, llm, orbit, forge):
    providers.override("forge_client", fake := FakeForge())
    task_id = await _run(user, project, orbit)
    before = await _copies(task_id)
    assert before["references"] and before["blocks"] and before["checkpoint"]  # the copies exist, and are readable

    async with db.session_scope() as session:
        effects = await forget.forget_source(session, document_id=DOC, project_slug="forge", actor_id=None)
    assert effects["tasks"] >= 1 and effects["checkpoints"] >= 1 and effects["references"] >= 1

    assert not any((await _copies(task_id)).values())  # nowhere: references, messages, events, tools, input, checkpoint
    assert await _checkpoint(task_id) is None
    artifact = await _artifact_of(task_id)
    assert artifact.review_requested_at is not None and artifact.review_reason == "source_removed"  # marked, not purged
    async with db.session_scope() as session:
        task = await session.get(Task, uuid.UUID(task_id))
        assert task.input.get("forgotten_at") and "provided_context" not in task.input
        assert (await session.scalars(select(ForgetRequest).where(ForgetRequest.scope == "source"))).first() is not None
    assert f"run-{task_id}" in fake.deleted  # FORGE was asked to delete the run it received


async def test_a_capture_waiting_for_forge_is_emptied_and_never_sent(user, project, llm, orbit, forge):
    from nova.infra.models import ForgeOutbox

    providers.override("forge_client", FakeForge())
    task_id = await _run(user, project, orbit)
    async with db.session_scope() as session:
        row = await session.scalar(select(ForgeOutbox).where(ForgeOutbox.task_id == task_id))
        if row is None:
            row = ForgeOutbox(task_id=task_id, idempotency_key=f"nova-task:{task_id}")
            session.add(row)
        row.status, row.payload = "pending", {"record": {"context": MARKER}}
    async with db.session_scope() as session:
        await forget.forget_source(session, document_id=DOC, project_slug="forge", actor_id=None)
    async with db.session_scope() as session:
        row = await session.scalar(select(ForgeOutbox).where(ForgeOutbox.task_id == task_id))
    assert row.payload == {} and row.status == "skipped"


async def test_other_sources_of_a_reference_are_kept_out_of_replays_but_not_erased(user, project, llm, orbit, forge):
    providers.override("forge_client", FakeForge())
    task_id = await _run(user, project, orbit)
    async with db.session_scope() as session:
        ref = await session.scalar(
            select(ContextRetrievalReference).where(ContextRetrievalReference.task_id == uuid.UUID(task_id))
        )
        kept = dict(
            ref.items[0], ref_id="chunk-kept", document_id="doc-kept", title="Kept", excerpt="KEPT-EXCERPT", citation="S2"
        )
        ref.items = [*ref.items, kept]
    async with db.session_scope() as session:
        await forget.forget_source(session, document_id=DOC, project_slug="forge", actor_id=None)
    async with db.session_scope() as session:
        ref = await session.scalar(
            select(ContextRetrievalReference).where(ContextRetrievalReference.task_id == uuid.UUID(task_id))
        )
    assert [i["document_id"] for i in ref.items] == ["doc-kept"] and ref.revoked_at is not None and ref.query == ""


async def test_the_purge_policy_deletes_the_derived_artifact(user, project, llm, orbit, forge, monkeypatch):
    providers.override("forge_client", FakeForge())
    monkeypatch.setattr(get_settings(), "forget_artifacts", "purge")
    task_id = await _run(user, project, orbit)
    artifact = await _artifact_of(task_id)
    async with db.session_scope() as session:
        effects = await forget.forget_source(session, document_id=DOC, project_slug="forge", actor_id=None)
    assert effects["artifacts_purged"] >= 1
    assert await _artifact_of(task_id) is None
    async with db.session_scope() as session:
        assert await session.scalar(select(ArtifactVersion.id).where(ArtifactVersion.artifact_id == artifact.id)) is None


async def test_a_forgotten_run_cannot_be_replayed_with_its_original_context(user, project, llm, orbit, forge):
    providers.override("forge_client", FakeForge())
    task_id = await _run(user, project, orbit)
    async with db.session_scope() as session:
        await forget.forget_source(session, document_id=DOC, project_slug="forge", actor_id=None)
    async with db.session_scope() as session:
        try:
            await create_replay(session, user, task_id, ReplayOptions(context="original"))
        except ReplayError as exc:
            assert exc.code == "forgotten"
        else:
            raise AssertionError("the original context was erased: it cannot be replayed")
        replay = await create_replay(session, user, task_id, ReplayOptions(context="none"))  # nothing of it is reused
        assert "provided_context" not in replay.input


async def test_forge_that_cannot_delete_yet_is_asked_again_until_it_acknowledges(user, project, llm, orbit, forge):
    fake = FakeForge()
    fake.error = ForgeError(405, "method not allowed")  # FORGE has no erasure endpoint yet
    providers.override("forge_client", fake)
    task_id = await _run(user, project, orbit)
    async with db.session_scope() as session:
        await forget.forget_source(session, document_id=DOC, project_slug="forge", actor_id=None)
    async with db.session_scope() as session:
        request = await session.scalar(select(ForgeErasureRequest).where(ForgeErasureRequest.run_id == f"run-{task_id}"))
        assert request.status == "pending" and request.attempts == 1 and "405" in request.last_error
        assert await session.scalar(select(IntegrationReference.id).where(IntegrationReference.nova_id == task_id)) is None

    fake.error = None  # FORGE now supports it
    assert await forget.deliver_forge_erasures() >= 1
    async with db.session_scope() as session:
        request = await session.scalar(select(ForgeErasureRequest).where(ForgeErasureRequest.run_id == f"run-{task_id}"))
        assert request.status == "acknowledged" and request.acknowledged_at is not None
    assert fake.deleted.count(f"run-{task_id}") == 1


async def test_forgetting_a_project_erases_every_copy_of_its_context(user, project, llm, orbit, forge):
    providers.override("forge_client", FakeForge())
    first = await _run(user, project, orbit)
    second = await _run(user, project, orbit, title="Another synthetic doc")
    async with db.session_scope() as session:
        effects = await forget.forget_project(session, project_slug="forge", actor_id=None)
    assert effects["tasks"] >= 2
    for task_id in (first, second):
        assert not any((await _copies(task_id)).values())
    async with db.session_scope() as session:
        left = await session.scalars(
            select(ContextRetrievalReference.id).where(ContextRetrievalReference.project_slug == "forge")
        )
        assert left.first() is None


async def test_forgetting_a_user_erases_only_what_was_served_to_that_user(user, project, llm, orbit, forge):
    providers.override("forge_client", FakeForge())
    task_id = await _run(user, project, orbit)
    async with db.session_scope() as session:
        other = User(subject=f"other-{uuid.uuid4()}", email=f"{uuid.uuid4().hex[:6]}@example.com", display_name="Other")
        session.add(other)
        await session.flush()
        kept = ContextRetrievalReference(user_id=other.id, project_slug="forge", items=[{"citation": "S1"}])
        session.add(kept)
        await session.flush()
        kept_id = kept.id
    async with db.session_scope() as session:
        await forget.forget_user(session, user_id=user.user_id, actor_id=None)
    assert not any((await _copies(task_id)).values())
    async with db.session_scope() as session:
        assert await session.get(ContextRetrievalReference, kept_id) is not None


async def test_an_orbit_forgotten_event_runs_the_forget(user, project, llm, orbit, forge, app):  # noqa: F811
    providers.override("forge_client", fake := FakeForge())
    task_id = await _run(user, project, orbit)
    response = await _send(app, "document.forgotten", "document", DOC)
    assert response.status_code == 200
    effects = response.json()["effects"]
    assert effects["forgotten_tasks"] >= 1 and effects["checkpoints"] >= 1
    assert not any((await _copies(task_id)).values())
    assert (await _artifact_of(task_id)).review_reason in ("source_removed", "document.forgotten")
    assert f"run-{task_id}" in fake.deleted
    # an ACL change only revokes: nothing is erased
    second = await _run(user, project, orbit, title="Restricted later")
    changed = await _send(app, "document.acl_changed", "document", DOC)
    assert changed.status_code == 200 and "forgotten_tasks" not in changed.json()["effects"]
    assert (await _copies(second))["checkpoint"] == 1


async def test_only_an_administrator_can_ask_for_a_forget(app, user, project, llm, orbit, forge):  # noqa: F811
    providers.override("forge_client", FakeForge())
    member, _ = await _http_client(app, "member")
    assert (await member.post("/api/v1/admin/forget", json={"scope": "source", "document_id": DOC})).status_code == 403
    assert (await member.get("/api/v1/admin/forget")).status_code == 403
    admin, admin_id = await _http_client(app, "admin")
    async with db.session_scope() as session:
        (await session.get(User, uuid.UUID(admin_id))).is_admin = True
    task_id = await _run(user, project, orbit)
    invalid = await admin.post("/api/v1/admin/forget", json={"scope": "source"})
    assert invalid.status_code == 422
    done = await admin.post("/api/v1/admin/forget", json={"scope": "source", "document_id": DOC, "project_slug": "forge"})
    assert done.status_code == 200 and done.json()["effects"]["tasks"] >= 1
    assert not any((await _copies(task_id)).values())
    listed = (await admin.get("/api/v1/admin/forget")).json()
    assert listed[0]["scope"] == "source" and listed[0]["status"] == "completed" and MARKER not in str(listed)


# --- Retention ----------------------------------------------------------------------------------------------------


async def test_retention_purges_old_references_events_and_checkpoints_and_counts_them(
    user, project, llm, orbit, forge, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "checkpoint_retention_days", 30)
    old, recent = await _run(user, project, orbit), await _run(user, project, orbit, title="Recent")
    long_ago = db.utcnow() - timedelta(days=45)
    async with db.session_scope() as session:
        task = await session.get(Task, uuid.UUID(old))
        task.finished_at = long_ago
        for ref in await session.scalars(select(ContextRetrievalReference).where(ContextRetrievalReference.task_id == task.id)):
            ref.created_at = db.utcnow() - timedelta(days=settings.context_reference_retention_days + 5)
        for event in await session.scalars(select(ExecutionEvent).where(ExecutionEvent.task_id == task.id)):
            event.created_at = db.utcnow() - timedelta(days=settings.execution_event_retention_days + 5)

    result = await maintenance.apply_retention()

    assert result["checkpoints"] >= 1 and result["context_references"] >= 1 and result["execution_events"] >= 1
    assert await _checkpoint(old) is None  # past the checkpoint retention: it can no longer be resumed or re-read
    assert await _checkpoint(recent) is not None  # a recent run keeps its checkpoint
    async with db.session_scope() as session:
        assert (await session.get(Task, uuid.UUID(old))).input.get("checkpoint_purged_at")
    assert (await maintenance.apply_retention())["checkpoints"] == 0  # nothing is purged twice


async def test_checkpoint_retention_can_be_turned_off(user, project, llm, orbit, forge, monkeypatch):
    monkeypatch.setattr(get_settings(), "checkpoint_retention_days", 0)
    task_id = await _run(user, project, orbit)
    async with db.session_scope() as session:
        (await session.get(Task, uuid.UUID(task_id))).finished_at = db.utcnow() - timedelta(days=900)
    await maintenance.apply_retention()
    assert await _checkpoint(task_id) is not None


async def test_the_celery_beat_delivers_pending_erasures():
    from nova_worker.app import celery_app

    assert celery_app.conf.beat_schedule["deliver-forge-erasures"]["task"] == "nova.deliver_forge_erasures"
