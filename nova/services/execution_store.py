"""SQLAlchemy implementation of the agent's ``ExecutionStore`` port."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nova.agent.ports import ArtifactOutline, ArtifactSnapshot, StoredContextReference
from nova.domain.artifacts import ArtifactContent
from nova.domain.blocks import Block, ProgressLine
from nova.domain.context import ContextBundle, ContextItem, SnapshotRef
from nova.domain.enums import BlockType, EventType, NovaPhase, ProjectRole, StepStatus, role_at_least
from nova.domain.outputs import EvaluationReference, ExecutionPlan, TokenUsage, ToolRequest, ToolResult
from nova.domain.permissions import Principal
from nova.domain.skills import SkillSpec
from nova.infra.db import session_scope, utcnow
from nova.infra.events import Publisher, get_publisher
from nova.infra.models import (
    Artifact,
    ArtifactVersion,
    ContextRetrievalReference,
    ExecutionEvent,
    IntegrationReference,
    MessageBlock,
    ProjectMember,
    SkillExecution,
    Task,
    TaskStep,
    ToolExecution,
    Workflow,
    WorkflowExecution,
)
from nova.infra.redaction import redact_obj
from nova.services.access import AccessDenied, artifact_role


def _uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


async def emit_event(
    session: AsyncSession, publisher: Publisher, task_id: uuid.UUID, type_: EventType | str, payload: dict[str, Any]
) -> None:
    seq = (await session.scalar(select(func.max(ExecutionEvent.seq)).where(ExecutionEvent.task_id == task_id)) or 0) + 1
    session.add(ExecutionEvent(task_id=task_id, seq=seq, type=str(type_), payload=payload))
    await session.flush()
    await publisher.publish(str(task_id), {"seq": seq, "type": str(type_), **payload})


class SqlExecutionStore:
    def __init__(self, principal: Principal, publisher: Publisher | None = None) -> None:
        self.principal = principal
        self.publisher = publisher or get_publisher()

    # --- Streaming & progress ------------------------------------------------------------------

    async def set_phase(self, task_id: str, phase: NovaPhase, label: str) -> None:
        async with session_scope() as session:
            tid = _uuid(task_id)
            await session.execute(update(Task).where(Task.id == tid).values(phase=phase.value, phase_label=label))
            await emit_event(session, self.publisher, tid, EventType.status, {"phase": phase.value, "label": label})  # type: ignore[arg-type]

    async def is_paused(self, task_id: str) -> bool:
        async with session_scope() as session:
            return await session.scalar(select(Task.status).where(Task.id == _uuid(task_id))) == "paused"

    async def is_cancelled(self, task_id: str) -> bool:
        async with session_scope() as session:
            return await session.scalar(select(Task.status).where(Task.id == _uuid(task_id))) == "cancelled"

    async def upsert_block(self, task_id: str, message_id: str | None, block: Block) -> None:
        if message_id is None:
            return
        async with session_scope() as session:
            await self._upsert(session, _uuid(task_id), _uuid(message_id), block)  # type: ignore[arg-type]

    async def _upsert(self, session: AsyncSession, task_id: uuid.UUID, message_id: uuid.UUID, block: Block) -> None:
        row = await session.scalar(
            select(MessageBlock).where(MessageBlock.message_id == message_id, MessageBlock.key == block.key)
        )
        data = block.data
        if row is None:
            position = await session.scalar(select(func.max(MessageBlock.position)).where(MessageBlock.message_id == message_id))
            row = MessageBlock(
                message_id=message_id,
                key=block.key,
                position=(position if position is not None else -1) + 1,
                type=block.type.value,
                payload=data,
            )
            session.add(row)
        else:
            row.type, row.payload = block.type.value, data
        await session.flush()
        await emit_event(
            session,
            self.publisher,
            task_id,
            EventType.block,
            {
                "message_id": str(message_id),
                "block": {"key": block.key, "type": block.type.value, "position": row.position, "data": data},
            },
        )

    async def progress(self, task_id: str, message_id: str | None, line: ProgressLine) -> None:
        async with session_scope() as session:
            tid = _uuid(task_id)
            await emit_event(session, self.publisher, tid, EventType.progress, line.model_dump())  # type: ignore[arg-type]
            if message_id is None:
                return
            mid = _uuid(message_id)
            row = await session.scalar(select(MessageBlock).where(MessageBlock.message_id == mid, MessageBlock.key == "progress"))
            lines = list((row.payload or {}).get("lines", [])) if row else []
            existing = next((i for i, existing in enumerate(lines) if existing["key"] == line.key), None)
            if existing is None:
                lines.append(line.model_dump())
            else:
                lines[existing] = line.model_dump()
            await self._upsert(session, tid, mid, Block(key="progress", type=BlockType.progress, data={"lines": lines}))  # type: ignore[arg-type]

    # --- Plan / steps --------------------------------------------------------------------------

    async def save_plan(self, task_id: str, plan: ExecutionPlan) -> str:
        async with session_scope() as session:
            task = await session.get(Task, _uuid(task_id))
            assert task is not None
            workflow = Workflow(
                project_id=task.project_id,
                created_by=task.user_id,
                objective=plan.objective,
                steps=[
                    {"id": s.id, "title": s.title, "skill_id": s.skill_id, "skill_version": s.skill_version} for s in plan.steps
                ],
            )
            session.add(workflow)
            await session.flush()
            existing = {s.step_key: s for s in (await session.scalars(select(TaskStep).where(TaskStep.task_id == task.id))).all()}
            keys = [s.id for s in plan.steps]
            for key, row in existing.items():
                if key not in keys and row.status == StepStatus.pending:
                    await session.delete(row)
            for position, step in enumerate(plan.steps):
                row = existing.get(step.id)
                if row is None:
                    session.add(
                        TaskStep(
                            task_id=task.id,
                            position=position,
                            step_key=step.id,
                            title=step.title,
                            skill_id=step.skill_id,
                            skill_version=step.skill_version,
                            status=step.status.value,
                            report={"goal": step.goal, "rationale": step.rationale},
                        )
                    )
                else:
                    row.position, row.title = position, step.title
                    row.report = {**(row.report or {}), "goal": step.goal, "rationale": step.rationale}
            task.progress_total = len(plan.steps)
            task.progress_done = sum(1 for s in plan.steps if s.status in (StepStatus.completed, StepStatus.skipped))
            await session.execute(
                update(WorkflowExecution).where(WorkflowExecution.task_id == task.id).values(workflow_id=workflow.id)
            )
            await emit_event(
                session,
                self.publisher,
                task.id,
                EventType.task,
                {"progress_done": task.progress_done, "progress_total": task.progress_total},
            )
            return str(workflow.id)

    async def update_step(
        self,
        task_id: str,
        step_id: str,
        status: StepStatus,
        *,
        detail: str = "",
        artifact_id: str | None = None,
        report: dict[str, Any] | None = None,
    ) -> None:
        async with session_scope() as session:
            tid = _uuid(task_id)
            row = await session.scalar(select(TaskStep).where(TaskStep.task_id == tid, TaskStep.step_key == step_id))
            if row is None:
                return
            row.status = status.value
            if detail:
                row.detail = detail
            if artifact_id:
                row.artifact_id = _uuid(artifact_id)
            if report:  # what the orchestrator recorded about the step: goal, validation, handoff
                row.report = {**(row.report or {}), **report}
            if status == StepStatus.running and row.started_at is None:
                row.started_at = utcnow()
            if status in (StepStatus.completed, StepStatus.failed, StepStatus.skipped):
                row.finished_at = utcnow()
            await session.flush()
            done = await session.scalar(
                select(func.count())
                .select_from(TaskStep)
                .where(TaskStep.task_id == tid, TaskStep.status.in_([StepStatus.completed.value, StepStatus.skipped.value]))
            )
            await session.execute(update(Task).where(Task.id == tid).values(progress_done=done or 0))
            await session.execute(update(WorkflowExecution).where(WorkflowExecution.task_id == tid).values(current_step=step_id))
            await emit_event(
                session,
                self.publisher,
                tid,
                EventType.task,  # type: ignore[arg-type]
                {"step": step_id, "step_status": status.value, "detail": detail, "progress_done": done or 0},
            )

    # --- Context references --------------------------------------------------------------------

    async def record_context(
        self, *, task_id: str, user_id: str, conversation_id: str | None, query: str, bundle: ContextBundle
    ) -> str:
        async with session_scope() as session:
            ref = ContextRetrievalReference(
                task_id=_uuid(task_id),
                conversation_id=_uuid(conversation_id),
                user_id=_uuid(user_id),
                project_slug=bundle.project_slug,
                retrieval_id=bundle.retrieval_id,
                trace_id=bundle.trace_id,
                query=query[:4000],
                items=[i.model_dump(mode="json") for i in bundle.items],
                warnings=bundle.warnings,
                max_classification=bundle.max_classification,
                snapshot_name=bundle.snapshot.name if bundle.snapshot else None,
                snapshot_version=bundle.snapshot.version if bundle.snapshot else None,
            )
            session.add(ref)
            await session.flush()
            return str(ref.id)

    async def get_snapshot_reference(self, user_id: str, project_slug: str) -> SnapshotRef | None:
        from nova.services.orbit_snapshots import get_reference

        return await get_reference(user_id, project_slug)

    async def get_context_references(self, ref_ids: list[str], user_id: str) -> list[StoredContextReference]:
        ids = [i for i in (_uuid(r) for r in ref_ids) if i]
        if not ids:
            return []
        async with session_scope() as session:
            rows = (
                await session.scalars(
                    select(ContextRetrievalReference).where(
                        ContextRetrievalReference.id.in_(ids), ContextRetrievalReference.user_id == _uuid(user_id)
                    )
                )
            ).all()
            return [
                StoredContextReference(
                    id=str(r.id),
                    retrieval_id=r.retrieval_id,
                    project_slug=r.project_slug,
                    items=[ContextItem.model_validate(i) for i in r.items],
                    created_at=r.created_at.isoformat(),
                )
                for r in rows
            ]

    # --- Skills & tools ------------------------------------------------------------------------

    async def start_skill_execution(self, *, task_id: str, step_id: str, skill: SkillSpec, inputs: dict[str, Any]) -> str:
        async with session_scope() as session:
            row = SkillExecution(
                task_id=_uuid(task_id), step_key=step_id, skill_id=skill.id, skill_version=skill.version, input=redact_obj(inputs)
            )
            session.add(row)
            await session.flush()
            return str(row.id)

    async def finish_skill_execution(
        self,
        execution_id: str,
        *,
        status: str,
        output: dict[str, Any] | None,
        usage: TokenUsage,
        model: str | None,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        if not execution_id:
            return
        async with session_scope() as session:
            await session.execute(
                update(SkillExecution)
                .where(SkillExecution.id == _uuid(execution_id))
                .values(
                    status=status,
                    output=output,
                    model=model,
                    tokens_in=usage.input_tokens,
                    tokens_out=usage.output_tokens,
                    duration_ms=duration_ms,
                    error=error,
                )
            )

    async def record_tool_execution(
        self,
        *,
        task_id: str,
        skill_execution_id: str | None,
        request: ToolRequest,
        result: ToolResult,
        duration_ms: float,
        approved_by: str | None = None,
    ) -> None:
        async with session_scope() as session:
            session.add(
                ToolExecution(
                    task_id=_uuid(task_id),
                    skill_execution_id=_uuid(skill_execution_id),
                    tool=request.tool,
                    input=redact_obj(request.arguments),
                    output=redact_obj(result.output) if isinstance(result.output, dict) else None,
                    status=result.status,
                    approved_by=_uuid(approved_by),
                    duration_ms=duration_ms,
                    error=result.error,
                )
            )

    # --- Artifacts -----------------------------------------------------------------------------

    async def _snapshot(self, session: AsyncSession, artifact: Artifact) -> ArtifactSnapshot:
        version = await session.scalar(
            select(ArtifactVersion).where(
                ArtifactVersion.artifact_id == artifact.id, ArtifactVersion.version == artifact.current_version
            )
        )
        assert version is not None
        executions = (
            await session.scalars(
                select(ArtifactVersion.skill_execution_id).where(
                    ArtifactVersion.artifact_id == artifact.id, ArtifactVersion.skill_execution_id.is_not(None)
                )
            )
        ).all()
        return ArtifactSnapshot(
            artifact_id=str(artifact.id),
            type=artifact.type,
            title=artifact.title,
            version=artifact.current_version,
            content=ArtifactContent.model_validate(version.content),
            classification=artifact.classification,
            project_id=str(artifact.project_id) if artifact.project_id else None,
            skill_execution_ids=[str(e) for e in executions],
        )

    async def get_artifact(self, artifact_id: str, user_id: str) -> ArtifactSnapshot | None:
        aid = _uuid(artifact_id) if artifact_id else None
        if aid is None:
            return None
        async with session_scope() as session:
            artifact = await session.get(Artifact, aid)
            if artifact is None or (await artifact_role(session, artifact, self.principal)) is None:
                return None
            return await self._snapshot(session, artifact)

    async def list_artifact_outlines(
        self, user_id: str, *, project_id: str | None, ids: list[str] | None = None, limit: int = 10
    ) -> list[ArtifactOutline]:
        async with session_scope() as session:
            uid = _uuid(user_id)
            member_projects = select(ProjectMember.project_id).where(ProjectMember.user_id == uid)
            query = select(Artifact).where(
                or_(Artifact.owner_id == uid, Artifact.project_id.in_(member_projects)), Artifact.status != "archived"
            )
            if ids:
                query = query.where(Artifact.id.in_([i for i in (_uuid(x) for x in ids) if i]))
            elif project_id:
                query = query.where(Artifact.project_id == _uuid(project_id))
            rows = (await session.scalars(query.order_by(Artifact.updated_at.desc()).limit(limit))).all()
            outlines = []
            for artifact in rows:
                snap = await self._snapshot(session, artifact)
                outlines.append(
                    ArtifactOutline(
                        artifact_id=snap.artifact_id,
                        type=snap.type,
                        title=snap.title,
                        version=snap.version,
                        sections=list(snap.content.sections),
                        items=[{"id": i.id, "section": k, "title": i.title} for k, i in snap.content.all_items()],
                    )
                )
            return outlines

    async def save_artifact(
        self,
        *,
        task_id: str,
        user_id: str,
        artifact_id: str | None,
        project_id: str | None,
        conversation_id: str | None,
        content: ArtifactContent,
        changed_sections: list[str],
        skill_execution_id: str | None,
        summary: str,
        classification: int,
        proposed: bool = False,
    ) -> tuple[str, int]:
        async with session_scope() as session:
            if artifact_id:
                artifact = await session.get(Artifact, _uuid(artifact_id))
                if artifact is None or not role_at_least(
                    await artifact_role(session, artifact, self.principal), ProjectRole.editor
                ):
                    raise AccessDenied
            else:
                artifact = Artifact(
                    type=content.type,
                    title=content.title,
                    project_id=_uuid(project_id),
                    owner_id=_uuid(user_id),
                    conversation_id=_uuid(conversation_id),
                    task_id=_uuid(task_id),
                    current_version=0,
                    classification=classification,
                )
                session.add(artifact)
                await session.flush()
            version = (
                await session.scalar(select(func.max(ArtifactVersion.version)).where(ArtifactVersion.artifact_id == artifact.id))
                or 0
            ) + 1
            session.add(
                ArtifactVersion(
                    artifact_id=artifact.id,
                    version=version,
                    content=content.model_dump(mode="json"),
                    changed_sections=changed_sections,
                    author_type="nova",
                    author_id=None,
                    skill_execution_id=_uuid(skill_execution_id),
                    task_id=_uuid(task_id),
                    summary=summary,
                    state="proposed" if proposed else "current",
                )
            )
            if not proposed:
                await session.execute(
                    update(ArtifactVersion)
                    .where(
                        ArtifactVersion.artifact_id == artifact.id,
                        ArtifactVersion.state == "current",
                        ArtifactVersion.version != version,
                    )
                    .values(state="superseded")
                )
                artifact.current_version = version
                artifact.title = content.title
            artifact.classification = max(artifact.classification, classification)
            artifact.updated_at = utcnow()
            return str(artifact.id), version

    async def promote_proposed_version(self, artifact_id: str, version: int, user_id: str) -> None:
        async with session_scope() as session:
            artifact = await session.get(Artifact, _uuid(artifact_id))
            if artifact is None or not role_at_least(await artifact_role(session, artifact, self.principal), ProjectRole.editor):
                raise AccessDenied
            await session.execute(
                update(ArtifactVersion)
                .where(ArtifactVersion.artifact_id == artifact.id, ArtifactVersion.state == "current")
                .values(state="superseded")
            )
            await session.execute(
                update(ArtifactVersion)
                .where(ArtifactVersion.artifact_id == artifact.id, ArtifactVersion.version == version)
                .values(state="current")
            )
            artifact.current_version = version
            artifact.updated_at = utcnow()

    async def discard_proposed_version(self, artifact_id: str, version: int, user_id: str) -> None:
        async with session_scope() as session:
            await session.execute(
                update(ArtifactVersion)
                .where(
                    ArtifactVersion.artifact_id == _uuid(artifact_id),
                    ArtifactVersion.version == version,
                    ArtifactVersion.state == "proposed",
                )
                .values(state="rejected")
            )

    async def save_evaluation_reference(self, task_id: str, reference: EvaluationReference) -> None:
        async with session_scope() as session:
            row = await session.scalar(
                select(IntegrationReference).where(
                    IntegrationReference.system == "forge",
                    IntegrationReference.kind == "evaluation",
                    IntegrationReference.nova_type == "task",
                    IntegrationReference.nova_id == task_id,
                )
            )
            data = reference.model_dump(mode="json")
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
