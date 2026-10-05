"""Typed LangGraph state of one NOVA execution (checkpointed after every node)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from nova.domain.artifacts import ArtifactReference, SectionContent
from nova.domain.context import ContextItem
from nova.domain.enums import AutonomyMode, ExecutionOrigin, NovaPhase
from nova.domain.outputs import (
    ExecutionPlan,
    IntentClassification,
    MissingInput,
    TokenUsage,
    ToolRequest,
    ToolResult,
)
from nova.domain.skills import SelectedSkill


class ContextIssue(BaseModel):
    code: str
    message: str
    retryable: bool = False


class StepOutput(BaseModel):
    """Progress of one plan step (one Skill). Each Skill sub-step is a separate graph iteration."""

    step_id: str
    skill_id: str
    skill_version: str
    skill_execution_id: str | None = None
    artifact_type: str
    target_artifact_id: str | None = None  # existing Artifact updated by this step
    artifact_id: str | None = None  # saved Artifact
    artifact_version: int | None = None
    edit_sections: list[str] = Field(default_factory=list)  # artifact-edit: sections the user targets
    substep_index: int = 0
    summaries: list[str] = Field(default_factory=list)
    sections: dict[str, SectionContent] = Field(default_factory=dict)  # validated, normalized
    id_scope: list[str] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    dropped_citations: int = 0
    revisions: int = 0  # revisions requested by the Validation agent
    validation: dict[str, Any] | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    duration_ms: float = 0.0
    done: bool = False


class ApprovalRequest(BaseModel):
    id: str
    action: Literal["confirm_workflow", "apply_artifact_changes", "external_write"]
    title: str
    description: str
    tool_request: ToolRequest | None = None
    artifact_id: str | None = None
    proposed_version: int | None = None


class Answer(BaseModel):
    text: str
    citations: list[str] = Field(default_factory=list)  # context labels
    provenance: list[dict[str, Any]] = Field(default_factory=list)  # resolved citations (explain_provenance)
    follow_ups: list[str] = Field(default_factory=list)


class ExecutionError(BaseModel):
    node: str
    code: str
    message: str
    retryable: bool = False


class NovaState(BaseModel):
    # Identity & routing
    task_id: str
    user_id: str
    conversation_id: str | None = None
    message_id: str | None = None  # NOVA reply message that receives the blocks
    project_id: str | None = None
    project_slug: str | None = None  # ORBIT project slug (context scope)
    origin: ExecutionOrigin = ExecutionOrigin.interactive
    autonomy: AutonomyMode = AutonomyMode.assist

    # Input
    intent: str
    history: list[dict[str, str]] = Field(default_factory=list)  # recent turns {role, text}
    active_artifact_id: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    skill_refs: list[str] = Field(default_factory=list)  # explicit /skill references
    edit_target: dict[str, Any] | None = None  # {"artifact_id", "sections"} — regenerate button, no classification
    context_mode: Literal["auto", "explicit", "none"] = "auto"
    pinned_context_ref_ids: list[str] = Field(default_factory=list)
    excluded_context_refs: list[str] = Field(default_factory=list)
    attachments: list[dict[str, str]] = Field(default_factory=list)  # {name, text}
    provided_context: list[ContextItem] = Field(default_factory=list)  # FORGE protocol context
    preferences: dict[str, Any] = Field(default_factory=dict)
    # Lessons of the agents' policies applied to this execution ({profile: AgentLearning}), snapshotted at start
    learning: dict[str, Any] = Field(default_factory=dict)
    agent_scope: str | None = None  # restricts planning to one specialist agent's Skills (FORGE training runs)
    subject: str | None = None  # names the deliverables (a goal's title), instead of deriving it from the request

    # Understanding & context
    classification: IntentClassification | None = None
    context_retrieval_id: str | None = None
    context_reference_id: str | None = None  # context_retrieval_references.id
    context_items: list[ContextItem] = Field(default_factory=list)
    context_warnings: list[str] = Field(default_factory=list)
    context_issue: ContextIssue | None = None

    # Planning & execution
    plan: ExecutionPlan | None = None
    selected_skills: list[SelectedSkill] = Field(default_factory=list)
    current_step: str | None = None
    user_inputs: dict[str, str] = Field(default_factory=dict)
    pending_questions: list[MissingInput] = Field(default_factory=list)
    step_outputs: dict[str, StepOutput] = Field(default_factory=dict)
    pending_tool_requests: list[ToolRequest] = Field(default_factory=list)
    tool_iterations: int = 0

    # Results
    artifacts: list[ArtifactReference] = Field(default_factory=list)
    answer: Answer | None = None
    requires_approval: bool = False
    approval: ApprovalRequest | None = None
    approval_decision: Literal["approved", "rejected"] | None = None

    # Status & telemetry
    phase: NovaPhase = NovaPhase.idle
    status: Literal["running", "waiting_user", "completed", "failed", "cancelled"] = "running"
    errors: list[ExecutionError] = Field(default_factory=list)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    trace_id: str | None = None
    model: str | None = None
