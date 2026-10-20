"""ORBIT revocation events: what NOVA keeps from a source ORBIT forgot or restricted (NOV-80 contract, NOV-81).

ORBIT tells NOVA (signed webhook, ids and levels only, never content) that a document or memory item was forgotten,
that who may read it changed, that a member was removed or an agent key revoked. NOVA then:

* marks the retrieval references holding that source as *revoked*: never served again (pinned context, replay with
  the original context, citations), whatever the user's clearance;
* flags the Artifacts citing them as *to review*: a banner, no export until a person has reviewed them;
* for a removed member, drops the delegated ORBIT session (relinking needed) and falls back to the default clearance;
* for a revoked agent key, stops using the project key (until it is rotated, or ORBIT still accepts it).

Every effect is audited. Effects are idempotent: an event can be received twice or replayed by an administrator.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Text, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.config import get_settings
from nova.infra import scope
from nova.infra.db import aware, utcnow
from nova.infra.models import (
    Artifact,
    ArtifactVersion,
    ContextRetrievalReference,
    IntegrationReference,
    OrbitAccount,
    OrbitEvent,
    Project,
    ProjectReference,
    User,
)
from nova.services import delegation, workspaces
from nova.services.audit import audit

#: Events that make a source unreadable for what NOVA kept: the extracts holding it are revoked.
SOURCE_EVENTS = frozenset(
    {
        "document.forgotten",
        "memory.forgotten",
        "document.acl_changed",
        "memory.acl_changed",
        "document.classification_changed",
    }
)
FORGET_EVENTS = frozenset({"document.forgotten", "memory.forgotten"})
ACCESS_EVENTS = frozenset({"member.removed"})
KEY_EVENTS = frozenset({"agent.revoked"})
HANDLED = SOURCE_EVENTS | ACCESS_EVENTS | KEY_EVENTS
MAX_BODY = 64 * 1024
CHUNK = 40  # reference ids per Artifact search


class RevocationError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class OrbitProject(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str | None = None
    slug: str | None = None


class OrbitEventIn(BaseModel):
    """The payload of NOV-80 (``webhook_payload``): ids, levels and a timestamp; extra fields are ignored."""

    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=1, max_length=80)
    type: str = Field(min_length=1, max_length=60)
    project: OrbitProject = Field(default_factory=OrbitProject)
    target_type: str = Field(default="", max_length=20)
    target_id: str = Field(default="", max_length=80)
    # The workspace ORBIT says the event is about (ADR 001 §3; signed with the rest of the payload). Absent today.
    orion_workspace_id: str | None = Field(default=None, max_length=64)
    created_at: datetime | None = None
    effective_at: datetime | None = None
    old_classification: int | None = None
    new_classification: int | None = None


def sign(secret: str, body: bytes) -> str:
    """ORBIT's ``X-Orbit-Signature``: ``sha256=<hex HMAC-SHA256(secret, body)>`` (also used by the tests)."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(secret: str, body: bytes, header: str) -> bool:
    return bool(secret) and hmac.compare_digest(sign(secret, body).encode(), header.strip().encode())


def parse(raw: dict[str, Any]) -> OrbitEventIn:
    try:
        return OrbitEventIn.model_validate(raw)
    except ValidationError as exc:
        raise RevocationError("invalid_event", "The event does not follow the expected format.") from exc


async def receive(session: AsyncSession, event: OrbitEventIn, delivery_id: str) -> tuple[str, dict[str, int]]:
    """Record and apply one event. ``(status, effects)``: ``processed``, ``duplicate`` or ``ignored``."""
    if event.type not in HANDLED:
        return "ignored", {}
    if not event.target_id:
        raise RevocationError("invalid_event", "The event has no target.")
    max_age = get_settings().orbit_webhook_max_age_seconds
    if max_age and event.created_at and (utcnow() - aware(event.created_at)).total_seconds() > max_age:
        raise RevocationError("stale_event", "The event is too old to be accepted.")
    with scope.platform_scope():  # a delivery id is unique whatever the workspace
        existing = await session.scalar(select(OrbitEvent.id).where(OrbitEvent.delivery_id == delivery_id))
    if existing is not None:
        return "duplicate", {}
    targets = await event_workspaces(session, event)
    row = OrbitEvent(
        delivery_id=delivery_id,
        type=event.type,
        project_slug=event.project.slug,
        target_type=event.target_type,
        target_id=event.target_id,
        payload=event.model_dump(mode="json"),
        workspace_id=targets[0] if targets else None,
    )
    session.add(row)
    await session.flush()
    if not targets:  # off: one pass, nothing scoped (what has always happened)
        return "processed", await apply(session, row)
    effects: dict[str, int] = {}
    for workspace in targets:  # a slug known in several workspaces revokes in each, each under its own scope
        with scope.workspace_scope(workspace):
            for key, value in (await apply(session, row)).items():
                effects[key] = effects.get(key, 0) + value
    row.effects = effects
    return "processed", effects


async def event_workspaces(session: AsyncSession, event: OrbitEventIn) -> list[uuid.UUID]:
    """The workspaces an event applies to; empty with ``off`` (nothing is scoped).

    The signed payload's ``orion_workspace_id`` when ORBIT sends one; else the workspaces whose NOVA projects reference
    this ORBIT project; else the default workspace. Never a header or a query parameter.
    """
    if not workspaces.enabled():
        return []
    if event.orion_workspace_id:
        claimed = workspaces.as_uuid(event.orion_workspace_id)
        if claimed is None:
            raise RevocationError("invalid_event", "The event names an invalid workspace.")
        return [claimed]
    if event.project.slug:
        with scope.platform_scope():
            found = await session.scalars(
                select(Project.workspace_id)
                .join(ProjectReference, ProjectReference.project_id == Project.id)
                .where(ProjectReference.system == "orbit", ProjectReference.external_id == event.project.slug)
                .distinct()
            )
            known = sorted(found.all())
        if known:
            return known
    return [scope.default_workspace_id()]


async def apply(session: AsyncSession, row: OrbitEvent, *, replayed: bool = False) -> dict[str, int]:
    """Run the effects of a stored event (idempotent); the outcome is kept on the event."""
    try:
        if row.type in SOURCE_EVENTS:
            effects = await _revoke_sources(session, row, await _matching_references(session, row))
            if row.type in FORGET_EVENTS:  # forgotten, not just restricted: nothing readable may be kept (NOV-98)
                from nova.services import forget

                erased = await forget.forget_source(
                    session,
                    document_id=row.target_id if row.target_type == "document" else None,
                    memory_item_id=row.target_id if row.target_type == "memory" else None,
                    project_slug=row.project_slug,
                    actor_id=None,
                    origin="orbit_event",
                )
                effects = {**effects, "forgotten_tasks": erased["tasks"], "checkpoints": erased["checkpoints"]}
        elif row.type in ACCESS_EVENTS:
            effects = await _remove_member(session, row)
        else:
            effects = await _revoke_agent_key(session, row)
    except Exception as exc:
        row.status, row.error = "failed", f"{type(exc).__name__}"[:300]
        raise
    row.status, row.effects, row.error, row.processed_at = "processed", effects, None, utcnow()
    await audit(
        session,
        actor_id=None,
        action="orbit.revocation_replayed" if replayed else "orbit.revocation",
        target_type="orbit_event",
        target_id=row.target_id,
        summary=f"ORBIT {row.type}: {effects}",
        details={"type": row.type, "delivery": row.delivery_id, "project": row.project_slug, "effects": effects},
    )
    return effects


# --- Extracts and derived Artifacts --------------------------------------------------------------------------------


def _holds(item: dict[str, Any], row: OrbitEvent) -> bool:
    if row.target_type == "document":
        return item.get("document_id") == row.target_id
    return row.target_id in (item.get("memory_item_id"), item.get("ref_id"))


async def _matching_references(session: AsyncSession, row: OrbitEvent) -> list[ContextRetrievalReference]:
    query = select(ContextRetrievalReference)
    if row.project_slug:
        query = query.where(ContextRetrievalReference.project_slug == row.project_slug)
    refs = (await session.scalars(query)).all()
    return [r for r in refs if any(_holds(i, row) for i in r.items or [])]


async def _revoke_sources(session: AsyncSession, row: OrbitEvent, refs: list[ContextRetrievalReference]) -> dict[str, int]:
    now = utcnow()
    for ref in refs:
        if ref.revoked_at is None:
            ref.revoked_at, ref.revoked_reason = now, row.type
    artifacts = await flag_for_review(session, [str(r.id) for r in refs], row.type, project=row.project_slug)
    return {"references": len(refs), "artifacts": artifacts}


async def artifacts_citing(session: AsyncSession, ref_ids: list[str]) -> list[Artifact]:
    """Artifacts any of whose versions cites one of these retrieval references."""
    found: dict[uuid.UUID, Artifact] = {}
    for start in range(0, len(ref_ids), CHUNK):
        chunk = ref_ids[start : start + CHUNK]
        rows = await session.scalars(
            select(Artifact)
            .join(ArtifactVersion, ArtifactVersion.artifact_id == Artifact.id)
            .where(or_(*(cast(ArtifactVersion.content, Text).contains(r) for r in chunk)))
            .distinct()
        )
        found.update({a.id: a for a in rows})
    return list(found.values())


async def flag_for_review(session: AsyncSession, ref_ids: list[str], reason: str, *, project: str | None = None) -> int:
    """Artifacts citing one of these extracts: a banner, no export until reviewed. Returns how many."""
    found = await artifacts_citing(session, ref_ids)
    now = utcnow()
    for artifact in found:
        if artifact.review_requested_at is None:
            artifact.review_requested_at, artifact.review_reason = now, reason
            await audit(
                session,
                actor_id=None,
                action="artifact.review_requested",
                target_type="artifact",
                target_id=str(artifact.id),
                project_id=artifact.project_id,
                summary=f"{artifact.title}: a source was forgotten or its access changed in ORBIT",
                details={"reason": reason, "project": project},
            )
    return len(found)


def review_view(artifact: Artifact) -> dict[str, Any]:
    return {
        "pending": artifact.review_requested_at is not None,
        "reason": artifact.review_reason,
        "since": aware(artifact.review_requested_at).isoformat() if artifact.review_requested_at else None,
    }


async def mark_reviewed(session: AsyncSession, artifact: Artifact, actor_id: str) -> None:
    if artifact.review_requested_at is None:
        return
    reason = artifact.review_reason
    artifact.review_requested_at, artifact.review_reason = None, None
    await audit(
        session,
        actor_id=actor_id,
        action="artifact.reviewed",
        target_type="artifact",
        target_id=str(artifact.id),
        project_id=artifact.project_id,
        summary=f"{artifact.title}: reviewed after ORBIT revoked a source",
        details={"reason": reason},
    )


# --- Access: member removed, agent key revoked ---------------------------------------------------------------------


async def _remove_member(session: AsyncSession, row: OrbitEvent) -> dict[str, int]:
    accounts = (
        await session.scalars(
            select(OrbitAccount).join(User, User.id == OrbitAccount.user_id).where(OrbitAccount.orbit_user_id == row.target_id)
        )
    ).all()  # joined to the user: only the accounts of the workspace this event runs in
    now, sessions = utcnow(), 0
    refs: list[ContextRetrievalReference] = []
    for account in accounts:
        if account.token_ciphertext is not None:
            sessions += 1
        # The delegated session is dropped (relinking needed); until then the user holds the default clearance only
        account.token_ciphertext, account.expires_at = None, now
        account.clearance = get_settings().default_clearance
        account.revoked_at, account.revoked_reason = now, row.type
        delegation.drop_cached(account.user_id, row.project_slug)  # NOV-111: a delegated token for this project is gone too
        await audit(
            session,
            actor_id=None,
            action="orbit.session_revoked",
            target_type="orbit_account",
            target_id=str(account.user_id),
            summary="ORBIT removed this member: the delegated session was dropped",
            details={"project": row.project_slug},
        )
        query = select(ContextRetrievalReference).where(ContextRetrievalReference.user_id == account.user_id)
        if row.project_slug:
            query = query.where(ContextRetrievalReference.project_slug == row.project_slug)
        refs += list((await session.scalars(query)).all())
    for ref in refs:
        if ref.revoked_at is None:
            ref.revoked_at, ref.revoked_reason = now, row.type
    artifacts = await flag_for_review(session, [str(r.id) for r in refs], row.type, project=row.project_slug)
    return {"sessions": sessions, "references": len(refs), "artifacts": artifacts}


def _fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


async def _revoke_agent_key(session: AsyncSession, row: OrbitEvent) -> dict[str, int]:
    slug = row.project_slug
    key = get_settings().orbit_agent_key_map().get(slug or "")
    if not slug or not key:
        return {"agent_keys": 0}  # no key configured for this project: nothing NOVA uses was revoked
    data = {"fingerprint": _fingerprint(key), "revoked_at": utcnow().isoformat(), "event": row.delivery_id}
    # The configured key is one for the whole installation: its revocation is a platform record, not a workspace's
    record = await _key_record(session, slug)
    if record is None:
        session.add(
            scope.platform_record(
                IntegrationReference(
                    system="orbit",
                    kind="agent_revoked",
                    nova_type="project",
                    nova_id=slug,
                    external_id=row.target_id[:200],
                    data=data,
                )
            )
        )
    else:
        record.external_id, record.data = row.target_id[:200], data
    await audit(
        session,
        actor_id=None,
        action="orbit.agent_key_revoked",
        target_type="project",
        target_id=slug,
        summary=f"ORBIT revoked an agent key of project {slug}: NOVA stops using the configured key",
        details={"key": row.target_id},
    )
    return {"agent_keys": 1}


async def _key_record(session: AsyncSession, slug: str) -> IntegrationReference | None:
    with scope.platform_scope():  # platform record: visible from every workspace
        return await session.scalar(
            select(IntegrationReference).where(
                IntegrationReference.system == "orbit",
                IntegrationReference.kind == "agent_revoked",
                IntegrationReference.nova_type == "project",
                IntegrationReference.nova_id == slug,
            )
        )


async def agent_key_revoked(session: AsyncSession, slug: str, key: str) -> bool:
    """Is this very key the one ORBIT revoked? A rotated key (another fingerprint) is not."""
    record = await _key_record(session, slug)
    return record is not None and record.data.get("fingerprint") == _fingerprint(key)


async def restore_agent_key(session: AsyncSession, slug: str) -> bool:
    """ORBIT still accepts the configured key (the revoked one was another): use it again. Audited."""
    record = await _key_record(session, slug)
    if record is None:
        return False
    await session.delete(record)
    await audit(
        session,
        actor_id=None,
        action="orbit.agent_key_restored",
        target_type="project",
        target_id=slug,
        summary=f"ORBIT accepts the agent key of project {slug} again: it is used again",
    )
    return True
