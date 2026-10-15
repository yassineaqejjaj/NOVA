"""Forgetting: erase every copy of ORBIT context NOVA kept, by source, project or user (NOV-98).

NOVA keeps copies of what ORBIT served: the retrieval references, the LangGraph checkpoints of the runs, the blocks
shown in conversations, the event stream, tool outputs, the inputs of FORGE-driven runs, the evaluations sent to FORGE,
and the Artifacts derived from it. ``docs/DATA_INVENTORY.md`` lists them with their retention.

* references: the forgotten items are removed (a whole project or user: the rows are deleted) and the query blanked;
* runs holding them: the LangGraph checkpoint is deleted (it carries the context), tool outputs are emptied, context
  items are scrubbed from the blocks, events and inputs, the run is marked ``forgotten_at`` (no replay with its
  original context);
* derived Artifacts: flagged "source removed" (``NOVA_FORGET_ARTIFACTS=mark``, the default) or deleted (``purge``);
* FORGE: a deletion request per captured run, kept until FORGE acknowledges it (retried by the beat).

This is technical scoping, not a legal compliance conclusion. Every request is recorded (what was done, never content).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from opentelemetry import metrics
from sqlalchemy import Text, cast, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.agent.runtime import open_checkpointer
from nova.config import get_settings
from nova.infra.db import session_scope, utcnow
from nova.infra.models import (
    Artifact,
    ArtifactComment,
    ArtifactVersion,
    ContextRetrievalReference,
    ExecutionEvent,
    ForgeErasureRequest,
    ForgetRequest,
    IntegrationReference,
    Message,
    MessageBlock,
    SkillExecution,
    Task,
    ToolExecution,
)
from nova.integrations.forge.client import ForgeError
from nova.services import providers, revocation
from nova.services.audit import audit

log = logging.getLogger(__name__)
_PURGED = metrics.get_meter("nova.forget").create_counter(
    "nova_forget_purged_total", description="Copies of ORBIT context erased, by kind (forget requests and retention)"
)
REASON = "source_removed"
DELIVERY_BATCH = 50


def count_purged(kind: str, n: int) -> None:
    """The metric of what was purged (also fed by the retention job)."""
    if n > 0:
        _PURGED.add(n, {"kind": kind})


# --- Scrubbing JSON copies -------------------------------------------------------------------------------------------


def _is_item(value: Any) -> bool:
    """A context item as NOVA stores it (``ContextItem``, or its rendering in a block / tool output)."""
    return isinstance(value, dict) and (("citation" in value and ("excerpt" in value or "ref_id" in value)) or "snippet" in value)


def scrub(value: Any, drop: Any) -> Any:
    """``value`` without the context items for which ``drop(item)`` is true (any depth)."""
    if isinstance(value, list):
        return [scrub(v, drop) for v in value if not (_is_item(v) and drop(v))]
    if isinstance(value, dict):
        return {k: scrub(v, drop) for k, v in value.items()}
    return value


def _matcher(document_id: str | None, memory_item_id: str | None):
    wanted = {i for i in (document_id, memory_item_id) if i}

    def drop(item: dict[str, Any]) -> bool:
        if not wanted:
            return True  # a whole project or user: every item goes
        return bool(wanted & {item.get("document_id"), item.get("memory_item_id"), item.get("ref_id")})

    return drop


# --- The erasure ---------------------------------------------------------------------------------------------------


async def _erase(
    session: AsyncSession,
    refs: list[ContextRetrievalReference],
    *,
    drop: Any,
    whole: bool,
    scope: str,
    target: str,
    origin: str,
    actor_id: str | None,
    extra_tasks: set[uuid.UUID] | None = None,
) -> dict[str, int]:
    settings = get_settings()
    task_ids = {r.task_id for r in refs if r.task_id} | (extra_tasks or set())
    ref_ids = [str(r.id) for r in refs]
    effects = dict.fromkeys(
        ("references", "tasks", "checkpoints", "blocks", "artifacts", "artifacts_purged", "forge_requests"), 0
    )
    errors: list[str] = []

    # 1. Derived Artifacts, found through the references before they are touched
    artifacts = await revocation.artifacts_citing(session, ref_ids)
    now = utcnow()
    for artifact in artifacts:
        if settings.forget_artifacts == "purge":
            await _purge_artifact(session, artifact)
            effects["artifacts_purged"] += 1
        else:
            if artifact.review_requested_at is None:
                artifact.review_requested_at = now
                await audit(
                    session,
                    actor_id=actor_id,
                    action="artifact.review_requested",
                    target_type="artifact",
                    target_id=str(artifact.id),
                    project_id=artifact.project_id,
                    summary=f"{artifact.title}: a source it cites was removed",
                    details={"reason": REASON},
                )
            artifact.review_reason = REASON
            effects["artifacts"] += 1

    # 2. References: the forgotten items (or the whole row) go, the query too
    for ref in refs:
        if whole:
            await session.delete(ref)
        else:
            ref.items = [i for i in ref.items or [] if not drop(i)]
            ref.query = ""
            ref.revoked_at, ref.revoked_reason = ref.revoked_at or now, ref.revoked_reason or REASON
    effects["references"] = len(refs)

    # 3. The runs that held them: blocks, events, tool outputs, inputs; FORGE requests; flag
    for task in (await session.scalars(select(Task).where(Task.id.in_(task_ids)))).all() if task_ids else []:
        task.input = {
            **scrub({k: v for k, v in (task.input or {}).items() if k != "pinned_context_ref_ids"}, drop),
            "forgotten_at": now.isoformat(),
        }
        effects["tasks"] += 1
        blocks = await session.scalars(
            select(MessageBlock).join(Message, Message.id == MessageBlock.message_id).where(Message.task_id == task.id)
        )
        for block in blocks:
            cleaned = scrub(block.payload, drop)
            if cleaned != block.payload:
                block.payload = {**cleaned, "forgotten": True} if block.type == "context_sources" else cleaned
                effects["blocks"] += 1
        for event in await session.scalars(select(ExecutionEvent).where(ExecutionEvent.task_id == task.id)):
            cleaned = scrub(event.payload, drop)
            if cleaned != event.payload:
                event.payload = cleaned
        for tool in await session.scalars(select(ToolExecution).where(ToolExecution.task_id == task.id)):
            tool.output = None  # what a retrieval tool returned: ORBIT content
        if settings.forget_artifacts == "purge":
            for skill_run in await session.scalars(select(SkillExecution).where(SkillExecution.task_id == task.id)):
                skill_run.output = None  # the derived content of the step
        effects["forge_requests"] += await _request_forge_erasure(session, task.id)

    # 4. Checkpoints (they carry the whole context of the run): last, once the database side is consistent
    await session.flush()
    if task_ids:
        try:
            async with open_checkpointer(settings.database_url) as saver:
                for task_id in task_ids:
                    await saver.adelete_thread(str(task_id))
                    effects["checkpoints"] += 1
        except Exception as exc:  # the request is recorded as partial: it must be repeated, never reported as done
            log.exception("Checkpoint deletion failed while forgetting %s", target)
            errors.append(f"checkpoints: {type(exc).__name__}")

    for kind in ("references", "checkpoints", "blocks", "artifacts_purged", "forge_requests"):
        count_purged(kind, effects[kind])
    session.add(
        ForgetRequest(
            scope=scope,
            target=target[:120],
            origin=origin,
            actor_id=uuid.UUID(actor_id) if actor_id else None,
            status="partial" if errors else "completed",
            effects=effects,
            error="; ".join(errors)[:300] or None,
        )
    )
    await audit(
        session,
        actor_id=actor_id,
        action="forget",
        target_type=scope,
        target_id=target[:120],
        summary=f"Forgot context ({scope}): {effects}",
        details={"origin": origin, "effects": effects, "errors": errors},
    )
    await deliver_forge_erasures(session)
    return {**effects, "errors": len(errors)}  # a partial request is recorded as such: repeat it (nothing is rolled back)


async def _purge_artifact(session: AsyncSession, artifact: Artifact) -> None:
    await session.execute(delete(ArtifactComment).where(ArtifactComment.artifact_id == artifact.id))
    await session.execute(delete(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact.id))
    await session.execute(
        delete(MessageBlock).where(MessageBlock.type == "artifact", cast(MessageBlock.payload, Text).contains(str(artifact.id)))
    )
    await session.delete(artifact)


async def _request_forge_erasure(session: AsyncSession, task_id: uuid.UUID) -> int:
    """FORGE received this run (an evaluation): ask it to delete it, and forget the link (the run id is kept aside)."""
    ref = await session.scalar(
        select(IntegrationReference).where(
            IntegrationReference.system == "forge",
            IntegrationReference.kind == "evaluation",
            IntegrationReference.nova_type == "task",
            IntegrationReference.nova_id == str(task_id),
        )
    )
    if ref is None:
        return 0
    if (
        ref.external_id
        and await session.scalar(select(ForgeErasureRequest.id).where(ForgeErasureRequest.run_id == ref.external_id)) is None
    ):
        session.add(ForgeErasureRequest(run_id=ref.external_id, task_id=task_id))
    await session.delete(ref)
    return 1 if ref.external_id else 0


async def deliver_forge_erasures(session: AsyncSession | None = None) -> int:
    """Send the pending deletion requests to FORGE; a 2xx (or 404: already gone) is the acknowledgement. Returns acked."""
    if session is None:
        async with session_scope() as own:
            return await deliver_forge_erasures(own)
    client = providers.forge_watch_client()
    if client is None:
        return 0  # FORGE is not configured: the requests wait
    await session.flush()
    pending = (
        await session.scalars(
            select(ForgeErasureRequest)
            .where(ForgeErasureRequest.status == "pending")
            .order_by(ForgeErasureRequest.created_at)
            .limit(DELIVERY_BATCH)
        )
    ).all()
    acknowledged = 0
    for request in pending:
        try:
            await client.delete_run(request.run_id)
        except ForgeError as exc:
            if exc.status != 404:
                request.attempts += 1
                request.last_error = ("unreachable" if exc.status == 0 else f"HTTP {exc.status}")[:300]
                continue
        except Exception as exc:
            request.attempts += 1
            request.last_error = type(exc).__name__
            continue
        request.status, request.acknowledged_at, request.last_error = "acknowledged", utcnow(), None
        request.attempts += 1
        acknowledged += 1
    return acknowledged


# --- Entry points ----------------------------------------------------------------------------------------------------


async def forget_source(
    session: AsyncSession,
    *,
    document_id: str | None = None,
    memory_item_id: str | None = None,
    project_slug: str | None = None,
    actor_id: str | None,
    origin: str = "admin",
) -> dict[str, int]:
    """Erase every copy of one ORBIT document or memory item."""
    if not (document_id or memory_item_id):
        raise ValueError("a document or a memory item is required")
    drop = _matcher(document_id, memory_item_id)
    query = select(ContextRetrievalReference)
    if project_slug:
        query = query.where(ContextRetrievalReference.project_slug == project_slug)
    refs = [r for r in (await session.scalars(query)).all() if any(drop(i) for i in r.items or [])]
    return await _erase(
        session,
        refs,
        drop=drop,
        whole=False,
        scope="source",
        target=document_id or memory_item_id or "",
        origin=origin,
        actor_id=actor_id,
    )


async def forget_project(
    session: AsyncSession, *, project_slug: str, actor_id: str | None, origin: str = "admin"
) -> dict[str, int]:
    """Erase every copy of the context ORBIT served for one project."""
    refs = list(
        (
            await session.scalars(select(ContextRetrievalReference).where(ContextRetrievalReference.project_slug == project_slug))
        ).all()
    )
    return await _erase(
        session,
        refs,
        drop=_matcher(None, None),
        whole=True,
        scope="project",
        target=project_slug,
        origin=origin,
        actor_id=actor_id,
    )


async def forget_user(session: AsyncSession, *, user_id: str, actor_id: str | None, origin: str = "admin") -> dict[str, int]:
    """Erase every copy of the context ORBIT served to one user."""
    refs = list(
        (
            await session.scalars(
                select(ContextRetrievalReference).where(ContextRetrievalReference.user_id == uuid.UUID(user_id))
            )
        ).all()
    )
    return await _erase(
        session, refs, drop=_matcher(None, None), whole=True, scope="user", target=user_id, origin=origin, actor_id=actor_id
    )
