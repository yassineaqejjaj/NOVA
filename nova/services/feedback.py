"""Feedback: stored in NOVA, forwarded to ORBIT (context quality) and FORGE (evaluation), linked to everything."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.agent.nodes.finalize import build_execution_record
from nova.agent.runtime import AgentRuntime, open_checkpointer
from nova.config import get_settings
from nova.domain.evaluation import FeedbackRecord
from nova.domain.outputs import EvaluationReference
from nova.domain.permissions import Principal
from nova.infra.models import (
    ArtifactVersion,
    ContextRetrievalReference,
    Feedback,
    IntegrationReference,
    Message,
    SkillExecution,
    Task,
)
from nova.services import providers
from nova.services.access import AccessDenied, require_artifact, require_task

log = logging.getLogger(__name__)


class FeedbackIn(BaseModel):
    rating: Literal["useful", "not_useful"]
    comment: str | None = Field(default=None, max_length=4000)
    message_id: str | None = None
    task_id: str | None = None
    artifact_id: str | None = None


async def submit_feedback(session: AsyncSession, principal: Principal, data: FeedbackIn) -> dict[str, Any]:
    task: Task | None = None
    conversation_id = None
    if data.message_id:
        message = await session.get(Message, uuid.UUID(data.message_id))
        if message is None:
            raise AccessDenied
        conversation_id = message.conversation_id
        if message.task_id:
            task = await require_task(session, message.task_id, principal)
    if data.task_id and task is None:
        task = await require_task(session, data.task_id, principal)
    artifact_id = uuid.UUID(data.artifact_id) if data.artifact_id else None
    if artifact_id:
        await require_artifact(session, artifact_id, principal)
    skill_id = skill_version = None
    if task:
        execution = await session.scalar(
            select(SkillExecution).where(SkillExecution.task_id == task.id).order_by(SkillExecution.created_at.desc())
        )
        if execution:
            skill_id, skill_version = execution.skill_id, execution.skill_version
    elif artifact_id:
        row = await session.execute(
            select(SkillExecution.skill_id, SkillExecution.skill_version, SkillExecution.task_id)
            .join(ArtifactVersion, ArtifactVersion.skill_execution_id == SkillExecution.id)
            .where(ArtifactVersion.artifact_id == artifact_id)
            .order_by(ArtifactVersion.version.desc())
        )
        first = row.first()
        if first:
            skill_id, skill_version, task_id = first
            task = await session.get(Task, task_id)

    feedback = Feedback(
        user_id=uuid.UUID(principal.user_id),
        rating=data.rating,
        comment=data.comment,
        conversation_id=conversation_id or (task.conversation_id if task else None),
        message_id=uuid.UUID(data.message_id) if data.message_id else None,
        task_id=task.id if task else None,
        skill_id=skill_id,
        skill_version=skill_version,
        artifact_id=artifact_id,
        trace_id=task.trace_id if task else None,
    )
    session.add(feedback)
    await session.flush()
    forwarded: dict[str, Any] = {"orbit": False, "forge": None}

    if task:
        # ORBIT: rate the context that was served for this execution.
        ref = await session.scalar(
            select(ContextRetrievalReference).where(
                ContextRetrievalReference.task_id == task.id, ContextRetrievalReference.retrieval_id.is_not(None)
            )
        )
        if ref and ref.project_slug and ref.retrieval_id:
            try:
                await providers.context().send_feedback(
                    principal.user_id, ref.project_slug, ref.retrieval_id, data.rating == "useful", data.comment
                )
                forwarded["orbit"] = True
            except Exception:
                log.warning("ORBIT feedback failed", exc_info=True)
        forwarded["forge"] = await _forge_feedback(
            session,
            task,
            FeedbackRecord(
                rating=data.rating,
                comment=data.comment,
                task_id=str(task.id),
                artifact_id=data.artifact_id,
                skill_id=skill_id,
                skill_version=skill_version,
            ),
        )
    feedback.forwarded = forwarded
    return {"id": str(feedback.id), "forwarded": forwarded}


async def _forge_feedback(session: AsyncSession, task: Task, record: FeedbackRecord) -> str | None:
    sink = providers.evaluation()
    if sink is None:
        return None
    row = await session.scalar(
        select(IntegrationReference).where(
            IntegrationReference.system == "forge",
            IntegrationReference.kind == "evaluation",
            IntegrationReference.nova_type == "task",
            IntegrationReference.nova_id == str(task.id),
        )
    )
    try:
        if row is None:
            if (
                get_settings().forge_capture_policy != "on_feedback"
                or record.rating != "not_useful"
                or task.status != "completed"
            ):
                return None
            async with open_checkpointer(get_settings().database_url) as checkpointer:
                state = await AgentRuntime(checkpointer).current_state(str(task.id))
            if state is None:
                return None
            from nova.services.executions import build_deps

            deps = await build_deps(str(task.user_id), task.project_id, task.origin)
            reference = await sink.capture(await build_execution_record(state, deps))
            if reference is None:
                return None
            row = IntegrationReference(
                system="forge",
                kind="evaluation",
                nova_type="task",
                nova_id=str(task.id),
                external_id=reference.run_id or "",
                data=reference.model_dump(mode="json"),
            )
            session.add(row)
        reference = EvaluationReference.model_validate(row.data)
        if reference.status in ("completed", "failed"):
            await sink.feedback(reference, record)
            return "sent"
        row.data = {**row.data, "pending_feedback": [*(row.data.get("pending_feedback") or []), record.model_dump(mode="json")]}
        return "pending"  # delivered by the refresh job once FORGE has evaluated the run
    except Exception:
        log.warning("FORGE feedback failed for task %s", task.id, exc_info=True)
        return "failed"
