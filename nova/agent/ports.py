"""Ports used by graph nodes. The agent never touches the database or HTTP directly."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from nova.domain.artifacts import ArtifactContent
from nova.domain.blocks import Block, ProgressLine
from nova.domain.context import ContextBundle, ContextItem, SnapshotRef
from nova.domain.enums import NovaPhase, StepStatus
from nova.domain.outputs import EvaluationReference, ExecutionPlan, TokenUsage, ToolRequest, ToolResult
from nova.domain.skills import SkillSpec


class ArtifactSnapshot(BaseModel):
    artifact_id: str
    type: str
    title: str
    version: int
    content: ArtifactContent
    classification: int = 0
    project_id: str | None = None
    skill_execution_ids: list[str] = Field(default_factory=list)


class ArtifactOutline(BaseModel):
    artifact_id: str
    type: str
    title: str
    version: int
    sections: list[str]
    items: list[dict[str, str]] = Field(default_factory=list)  # {id, section, title}


class StoredContextReference(BaseModel):
    id: str
    retrieval_id: str | None
    project_slug: str | None
    items: list[ContextItem]
    created_at: str | None = None


class ExecutionStore(Protocol):
    # Streaming & progress
    async def set_phase(self, task_id: str, phase: NovaPhase, label: str) -> None: ...
    async def is_cancelled(self, task_id: str) -> bool: ...

    async def is_paused(self, task_id: str) -> bool: ...
    async def upsert_block(self, task_id: str, message_id: str | None, block: Block) -> None: ...
    async def progress(self, task_id: str, message_id: str | None, line: ProgressLine) -> None: ...

    # Plan / steps
    async def save_plan(self, task_id: str, plan: ExecutionPlan) -> str: ...
    async def update_step(
        self,
        task_id: str,
        step_id: str,
        status: StepStatus,
        *,
        detail: str = "",
        artifact_id: str | None = None,
        report: dict[str, Any] | None = None,
    ) -> None: ...

    # Context references (what ORBIT served — not a copy of ORBIT)
    async def record_context(
        self, *, task_id: str, user_id: str, conversation_id: str | None, query: str, bundle: ContextBundle
    ) -> str: ...
    async def get_snapshot_reference(self, user_id: str, project_slug: str) -> SnapshotRef | None: ...

    async def get_context_references(self, ref_ids: list[str], user_id: str) -> list[StoredContextReference]: ...

    # Skills & tools
    async def start_skill_execution(self, *, task_id: str, step_id: str, skill: SkillSpec, inputs: dict[str, Any]) -> str: ...
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
    ) -> None: ...
    async def record_tool_execution(
        self,
        *,
        task_id: str,
        skill_execution_id: str | None,
        request: ToolRequest,
        result: ToolResult,
        duration_ms: float,
        approved_by: str | None = None,
    ) -> None: ...

    # Artifacts (permission-checked for user_id)
    async def get_artifact(self, artifact_id: str, user_id: str) -> ArtifactSnapshot | None: ...
    async def list_artifact_outlines(
        self, user_id: str, *, project_id: str | None, ids: list[str] | None = None, limit: int = 10
    ) -> list[ArtifactOutline]: ...
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
    ) -> tuple[str, int]: ...
    # Evaluation references (FORGE scenario/run ids — FORGE keeps the traces)
    async def save_evaluation_reference(self, task_id: str, reference: EvaluationReference) -> None: ...

    async def promote_proposed_version(self, artifact_id: str, version: int, user_id: str) -> None: ...
    async def discard_proposed_version(self, artifact_id: str, version: int, user_id: str) -> None: ...
