"""Outbox of FORGE captures: a finished run's capture is recorded first, then delivered, retried and never lost.

The intent is written before the run completes (``emit_forge_trace``), so an unavailable FORGE no longer loses it: the first
attempt happens right away, failures stay ``pending`` with an exponential backoff and are picked up by the worker
(``process_due``) until they succeed, are refused for good, or exhaust ``forge_outbox_max_attempts`` (``failed``: the failure
queue). One NOVA run has one row (``nova-task:<id>``, FORGE's idempotency key for observed runs) and a run already linked to
a FORGE run is never sent again. ``skipped`` = nothing was sent (classification guard, capture disabled).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nova.config import get_settings
from nova.domain.evaluation import EvaluationSink, ExecutionRecord
from nova.domain.outputs import EvaluationReference
from nova.infra.db import aware, session_scope, utcnow
from nova.infra.models import ForgeOutbox, IntegrationReference, Task
from nova.integrations.forge import guard
from nova.integrations.forge.client import ForgeError
from nova.services.workspaces import outbox_key

log = logging.getLogger(__name__)

LEASE = timedelta(minutes=5)  # a worker that claimed a row and died releases it after this
BACKOFF_BASE, BACKOFF_CAP = 30.0, 3600.0  # seconds: 30 s, 1 min, 2 min … 1 h
RETRYABLE_CLIENT_ERRORS = (408, 425, 429)


@asynccontextmanager
async def _scope(session: AsyncSession | None) -> AsyncIterator[AsyncSession]:
    if session is not None:
        yield session
    else:
        async with session_scope() as own:
            yield own


def key_of(task_id: str, workspace_id: uuid.UUID | str | None = None) -> str:
    """The outbox's deduplication key: ``nova-task:<id>``, with the workspace in it outside the default workspace."""
    return outbox_key(task_id, workspace_id)


async def _workspace_of(session: AsyncSession, task_id: str) -> uuid.UUID | None:
    try:
        return await session.scalar(select(Task.workspace_id).where(Task.id == uuid.UUID(task_id)))
    except ValueError:  # not a NOVA task id (a synthetic run): the default workspace
        return None


def _storable(record: ExecutionRecord, ceiling: int) -> dict[str, Any]:
    """What waits in the outbox: never the answer, and no text at all above the capture ceiling (it would not be sent)."""
    data = record.model_dump(mode="json")
    data["output_markdown"] = ""
    if guard.above_ceiling(record, ceiling) is not None:
        data["user_intent"] = ""
        data["context_documents"] = [
            {"id": d.get("id"), "classification": 3 if d.get("classification") is None else d["classification"]}
            for d in record.context_documents
        ]
    return data


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(BACKOFF_CAP, BACKOFF_BASE * 2 ** max(0, attempts - 1)))


async def enqueue_capture(
    record: ExecutionRecord, *, feedback: list[dict[str, Any]] | None = None, session: AsyncSession | None = None
) -> str:
    """Record the intent to capture ``record`` (idempotent per run); ``feedback`` waits for the capture, then is delivered."""
    async with _scope(session) as s:
        workspace_id = await _workspace_of(s, record.task_id)
        key = key_of(record.task_id, workspace_id)
        row = await s.scalar(select(ForgeOutbox).where(ForgeOutbox.idempotency_key == key))
        if row is not None:
            if feedback and row.status in ("pending", "failed"):
                row.payload = {**row.payload, "feedback": [*row.payload.get("feedback", []), *feedback]}
            return str(row.id)
        ceiling = get_settings().forge_max_capture_classification
        row = ForgeOutbox(
            task_id=record.task_id,
            **({"workspace_id": workspace_id} if workspace_id else {}),
            idempotency_key=key,
            status="pending",
            attempts=0,
            next_attempt_at=utcnow(),
            payload={"record": _storable(record, ceiling), "feedback": feedback or []},
        )
        s.add(row)
        await s.flush()
        return str(row.id)


async def _linked(task_id: str) -> str | None:
    """The FORGE run this NOVA run is already linked to (a capture that went through but was not marked)."""
    async with session_scope() as session:
        reference = await session.scalar(
            select(IntegrationReference.data).where(
                IntegrationReference.system == "forge",
                IntegrationReference.kind == "evaluation",
                IntegrationReference.nova_type == "task",
                IntegrationReference.nova_id == task_id,
            )
        )
    return (reference or {}).get("run_id")


async def _claim(outbox_id: uuid.UUID) -> ForgeOutbox | None:
    """Take the row for one attempt: only one worker wins, and only while the row is due."""
    now = utcnow()
    async with session_scope() as session:
        claimed = await session.execute(
            update(ForgeOutbox)
            .where(
                ForgeOutbox.id == outbox_id,
                ForgeOutbox.status == "pending",
                (ForgeOutbox.next_attempt_at.is_(None)) | (ForgeOutbox.next_attempt_at <= now),
            )
            .values(next_attempt_at=now + LEASE, attempts=ForgeOutbox.attempts + 1)
        )
        if claimed.rowcount != 1:
            return None
        row = await session.get(ForgeOutbox, outbox_id)
        assert row is not None
        session.expunge(row)
        return row


async def _settle(outbox_id: uuid.UUID, status: str, *, note: str | None = None, retry_in: timedelta | None = None) -> None:
    async with session_scope() as session:
        row = await session.get(ForgeOutbox, outbox_id)
        if row is None:
            return
        row.status, row.last_error = status, (note or "")[:300] or None
        if status == "pending":
            row.next_attempt_at = utcnow() + (retry_in or backoff(row.attempts))
        else:
            row.next_attempt_at, row.settled_at = None, utcnow()
            row.payload = {}  # settled: nothing is kept that was only there to be sent


async def _save_reference(task_id: str, reference: EvaluationReference, feedback: list[dict[str, Any]]) -> None:
    data = reference.model_dump(mode="json")
    if feedback and reference.status != "skipped":
        data["pending_feedback"] = feedback  # delivered by the refresh job once FORGE has evaluated the run
    async with session_scope() as session:
        row = await session.scalar(
            select(IntegrationReference).where(
                IntegrationReference.system == "forge",
                IntegrationReference.kind == "evaluation",
                IntegrationReference.nova_type == "task",
                IntegrationReference.nova_id == task_id,
            )
        )
        if row is None:
            session.add(
                IntegrationReference(
                    system="forge",
                    kind="evaluation",
                    nova_type="task",
                    nova_id=task_id,
                    external_id=reference.run_id or reference.scenario_id or "",
                    data=data,
                )
            )
        else:
            row.external_id, row.data = reference.run_id or row.external_id, data


def _permanent(exc: Exception) -> bool:
    return isinstance(exc, ForgeError) and 400 <= exc.status < 500 and exc.status not in RETRYABLE_CLIENT_ERRORS


async def deliver(outbox_id: str, sink: EvaluationSink | None) -> str | None:
    """One attempt to send a due row. Returns its status afterwards, ``None`` when it was not due or already taken."""
    oid = uuid.UUID(outbox_id)
    row = await _claim(oid)
    if row is None:
        return None
    task_id = row.task_id
    if await _linked(task_id):  # this run is already in FORGE: never a second observed run
        await _settle(oid, "sent")
        return "sent"
    if sink is None:
        await _settle(oid, "skipped", note="FORGE is not configured")
        return "skipped"
    try:
        record = ExecutionRecord.model_validate(row.payload["record"])
        reference = await sink.capture(record)
    except Exception as exc:
        message = getattr(exc, "message", None) or str(exc) or exc.__class__.__name__
        log.warning("FORGE capture of task %s failed (attempt %s): %s", task_id, row.attempts, message)
        if _permanent(exc) or row.attempts >= get_settings().forge_outbox_max_attempts:
            await _settle(oid, "failed", note=message)
            return "failed"
        await _settle(oid, "pending", note=message)
        return "pending"
    if reference is None:
        await _settle(oid, "skipped", note="FORGE capture is disabled")
        return "skipped"
    await _save_reference(task_id, reference, row.payload.get("feedback") or [])
    if reference.status == "skipped":
        await _settle(oid, "skipped", note=reference.note)
        return "skipped"
    await _settle(oid, "sent")
    return "sent"


async def process_due(sink: EvaluationSink | None, limit: int = 50) -> int:
    """Catch-up pass: attempt every pending row whose time has come. Returns how many were attempted."""
    async with session_scope() as session:
        due = (
            await session.scalars(
                select(ForgeOutbox.id)
                .where(
                    ForgeOutbox.status == "pending",
                    (ForgeOutbox.next_attempt_at.is_(None)) | (ForgeOutbox.next_attempt_at <= utcnow()),
                )
                .order_by(ForgeOutbox.created_at)
                .limit(limit)
            )
        ).all()
    attempted = 0
    for outbox_id in due:
        if await deliver(str(outbox_id), sink) is not None:
            attempted += 1
    return attempted


async def stats(session: AsyncSession) -> dict[str, Any]:
    """Counts per status and the age of the oldest row still waiting (pending or failed)."""
    counts = dict.fromkeys(("pending", "sent", "failed", "skipped"), 0)
    for status, n in (await session.execute(select(ForgeOutbox.status, func.count()).group_by(ForgeOutbox.status))).all():
        counts[status] = n
    oldest = await session.scalar(select(func.min(ForgeOutbox.created_at)).where(ForgeOutbox.status.in_(("pending", "failed"))))
    age = (utcnow() - aware(oldest)).total_seconds() if oldest else 0.0  # type: ignore[operator]
    return {**counts, "oldest_waiting_seconds": round(age, 1)}


def prometheus(data: dict[str, Any]) -> str:
    """The same numbers in Prometheus text exposition format."""
    lines = ["# HELP nova_forge_outbox_rows FORGE capture outbox rows by status", "# TYPE nova_forge_outbox_rows gauge"]
    lines += [f'nova_forge_outbox_rows{{status="{s}"}} {data[s]}' for s in ("pending", "sent", "failed", "skipped")]
    lines += [
        "# HELP nova_forge_outbox_oldest_waiting_seconds Age of the oldest capture still pending or failed",
        "# TYPE nova_forge_outbox_oldest_waiting_seconds gauge",
        f"nova_forge_outbox_oldest_waiting_seconds {data['oldest_waiting_seconds']}",
    ]
    return "\n".join(lines) + "\n"
