"""Replay: re-execute a past run with other context, model or lessons, as a new task.

A replay is a real run (it costs tokens), so it is bounded: the model must be on ``replay_models``, it never
asks questions or waits for confirmation, and it cannot write to external systems. The original run is never
touched; the replay links back through ``tasks.replay_of`` and its manifest records what was changed.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.config import get_settings
from nova.domain.context import SnapshotRef
from nova.domain.enums import AutonomyMode, ExecutionOrigin, TaskStatus
from nova.domain.permissions import Principal, may_read_classification
from nova.infra.models import ContextRetrievalReference, Task
from nova.services.access import require_task


class ReplayError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


class ReplayOptions(BaseModel):
    context: Literal["original", "live", "none"] = "original"  # the sources it saw / ORBIT again / none at all
    model: str | None = None
    snapshot: SnapshotRef | None = None  # live context only: ORBIT base snapshot instead of the user's reference
    learning_policy_id: str | None = None  # lessons of another agent policy instead of the active ones


TERMINAL = {TaskStatus.completed.value, TaskStatus.failed.value}
NEVER_WRITE = {"orbit.write": "never"}


async def create_replay(session: AsyncSession, principal: Principal, task_id: str, options: ReplayOptions) -> Task:
    original = await require_task(session, task_id, principal)
    if original.status not in TERMINAL:
        raise ReplayError("not_finished", "Only a finished run can be replayed.")
    settings = get_settings()
    if options.model and options.model not in settings.replay_models:
        raise ReplayError("model_not_allowed", f"Model “{options.model}” is not on the replay allow-list.")
    if options.snapshot and options.context != "live":
        raise ReplayError("invalid", "A snapshot only applies to a replay with live context.")

    task_input: dict[str, Any] = {
        k: v
        for k, v in (original.input or {}).items()
        if k not in ("learning", "learning_policy_id", "pinned_context_ref_ids", "excluded_context_refs")
    }
    overrides: dict[str, Any] = {"context": options.context}
    if options.context == "original":
        every = (
            await session.execute(
                select(ContextRetrievalReference.id, ContextRetrievalReference.items, ContextRetrievalReference.revoked_at).where(
                    ContextRetrievalReference.task_id == original.id
                )
            )
        ).all()
        # An extract ORBIT forgot or restricted since is never re-injected (NOV-81): the replay goes without it
        stored = [(ref_id, items) for ref_id, items, revoked_at in every if revoked_at is None]
        if len(stored) < len(every):
            if not stored:
                raise ReplayError("revoked", "Every source of this run was forgotten or restricted in ORBIT since.")
            overrides["revoked_sources"] = len(every) - len(stored)
        # The stored extracts are re-served without asking ORBIT again: the user's *current* clearance must cover them
        # (fail-closed; a replay with ``live`` context re-queries ORBIT with the rights of today).
        if any(not may_read_classification(principal, int(i.get("classification", 3))) for _, items in stored for i in items):
            raise ReplayError(
                "clearance",
                "This run used sources above your current clearance: replay it with live context instead.",
            )
        refs = [ref_id for ref_id, _ in stored]
        task_input["context_mode"] = "explicit"  # no new retrieval: re-use exactly what ORBIT served before
        task_input["pinned_context_ref_ids"] = [str(r) for r in refs]
    elif options.context == "live":
        task_input["context_mode"] = "auto"
        if options.snapshot:
            task_input["snapshot_override"] = options.snapshot.model_dump()
            overrides["snapshot"] = f"{options.snapshot.name}@v{options.snapshot.version or 'latest'}"
    else:
        task_input["context_mode"] = "none"
    if options.model:
        task_input["model_override"] = options.model
        overrides["model"] = options.model
    if options.learning_policy_id:
        task_input["learning_policy_id"] = options.learning_policy_id
        overrides["learning_policy_id"] = options.learning_policy_id

    task_input.update(
        {
            "origin": ExecutionOrigin.replay.value,
            "autonomy": AutonomyMode.assist.value,
            "conversation_id": None,  # nothing is posted into the user's conversation
            "message_id": None,
            "manifest_ids": {"replay_of": str(original.id)},
            "replay_overrides": overrides,
            "preferences": {**(task_input.get("preferences") or {}), "action_permissions": NEVER_WRITE},
        }
    )
    replay = Task(
        user_id=original.user_id,
        project_id=original.project_id,
        objective=original.objective,
        origin=ExecutionOrigin.replay.value,
        autonomy=AutonomyMode.assist.value,
        input=task_input,
        status=TaskStatus.queued.value,
        replay_of=original.id,
    )
    session.add(replay)
    await session.flush()
    return replay


async def list_replays(session: AsyncSession, principal: Principal, task_id: str) -> list[Task]:
    original = await require_task(session, task_id, principal)
    rows = await session.scalars(select(Task).where(Task.replay_of == original.id).order_by(Task.created_at))
    return list(rows)


def summary(task: Task) -> dict[str, Any]:
    """What a comparison needs from a replay: what changed, how it ended, what it cost."""
    return {
        "id": str(task.id),
        "replay_of": str(task.replay_of) if task.replay_of else None,
        "status": task.status,
        "overrides": (task.input or {}).get("replay_overrides") or {},
        "model": task.model,
        "usage": task.usage,
        "error": task.error,
        "manifest": task.run_manifest,
    }
