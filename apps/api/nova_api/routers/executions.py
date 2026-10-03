"""Live execution stream (SSE), answers/approvals, cancel and retry."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from nova.domain.enums import TaskStatus
from nova.infra.db import get_session, session_scope
from nova.infra.events import get_publisher
from nova.infra.models import ExecutionEvent, Task
from nova.services.access import require_task
from nova.services.audit import audit
from nova.services.dispatch import dispatch
from nova.services.execution_store import emit_event
from nova_api.auth import CurrentPrincipal
from nova_api.errors import ApiError

router = APIRouter(prefix="/executions", tags=["executions"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
TERMINAL = {"completed", "failed", "cancelled"}


class ResumeIn(BaseModel):
    """Answer to what the execution waits for: questions ``{key: answer}``, workflow ``{action, skill_ids?}``,
    approval ``{action: approve|reject}``."""

    value: dict[str, Any]


@router.get("/{task_id}")
async def execution(task_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    task = await require_task(session, task_id, principal)
    return {
        "id": str(task.id),
        "status": task.status,
        "phase": task.phase,
        "phase_label": task.phase_label,
        "waiting_for": task.waiting_for,
        "progress_done": task.progress_done,
        "progress_total": task.progress_total,
    }


@router.get("/{task_id}/events")
async def events(
    task_id: str, request: Request, principal: CurrentPrincipal, session: SessionDep, after: int = Query(0, ge=0)
) -> EventSourceResponse:
    """Replay persisted events after ``after`` then follow live ones. Ends after ``done`` when nothing waits."""
    task = await require_task(session, task_id, principal)
    tid = task.id

    async def stream() -> AsyncIterator[dict[str, Any]]:
        subscription = get_publisher().subscribe(str(tid)).__aiter__()
        first = asyncio.ensure_future(subscription.__anext__())  # subscribe before replaying (no gap)
        await asyncio.sleep(0)
        last = after
        async with session_scope() as s:
            rows = (
                await s.scalars(
                    select(ExecutionEvent)
                    .where(ExecutionEvent.task_id == tid, ExecutionEvent.seq > after)
                    .order_by(ExecutionEvent.seq)
                )
            ).all()
            status = await s.scalar(select(Task.status).where(Task.id == tid))
        for row in rows:
            last = row.seq
            yield {"id": str(row.seq), "event": row.type, "data": json.dumps({"seq": row.seq, "type": row.type, **row.payload})}
        if status in TERMINAL or status == "waiting_user":
            first.cancel()
            yield {"event": "end", "data": json.dumps({"status": status})}
            return
        pending = first
        try:
            while not await request.is_disconnected():
                event = await pending
                pending = asyncio.ensure_future(subscription.__anext__())
                if event.get("type") == "heartbeat":
                    yield {"event": "heartbeat", "data": "{}"}
                    continue
                if event.get("seq", 0) <= last:
                    continue
                last = event.get("seq", last)
                yield {"id": str(last), "event": event["type"], "data": json.dumps(event, default=str)}
                if event["type"] == "done":
                    yield {"event": "end", "data": json.dumps({"status": event.get("status")})}
                    return
        finally:
            pending.cancel()
            with contextlib.suppress(Exception):
                await subscription.aclose()

    return EventSourceResponse(stream(), ping=15)


@router.post("/{task_id}/resume", status_code=202)
async def resume(task_id: str, body: ResumeIn, principal: CurrentPrincipal, session: SessionDep) -> dict[str, str]:
    task = await require_task(session, task_id, principal)
    if task.status != TaskStatus.waiting_user or not task.waiting_for:
        raise ApiError(409, "not_waiting", "This task is not waiting for you.")
    kind = task.waiting_for.get("kind")
    if kind in ("approval", "confirm_workflow"):
        await audit(
            session,
            actor_id=principal.user_id,
            action=f"execution.{kind}",
            target_type="task",
            target_id=str(task.id),
            project_id=task.project_id,
            summary=f"{kind}: {body.value.get('action')}",
            details={"value": body.value},
        )
    task.status = TaskStatus.queued.value
    await session.commit()
    await dispatch(str(task.id), "resume", body.value)
    return {"status": "queued"}


@router.post("/{task_id}/cancel")
async def cancel(task_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, str]:
    """Cancellation is honored at the next node boundary (the current model call completes)."""
    task = await require_task(session, task_id, principal)
    if task.status in TERMINAL:
        return {"status": task.status}
    idle = task.status in (TaskStatus.waiting_user, TaskStatus.scheduled, TaskStatus.queued)
    task.status = TaskStatus.cancelled.value
    task.waiting_for = None
    if idle:  # no worker will observe it: close the stream now
        await emit_event(session, get_publisher(), task.id, "done", {"status": "cancelled"})
    await session.commit()
    return {"status": "cancelled"}


@router.post("/{task_id}/retry", status_code=202)
async def retry(task_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, str]:
    """Resume a failed task from its last good checkpoint (completed steps are kept)."""
    task = await require_task(session, task_id, principal)
    if task.status != TaskStatus.failed:
        raise ApiError(409, "not_failed", "Only failed tasks can be retried.")
    task.status, task.error = TaskStatus.queued.value, None
    await session.commit()
    await dispatch(str(task.id), "retry")
    return {"status": "queued"}
