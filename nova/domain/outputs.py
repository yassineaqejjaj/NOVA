"""Typed structured outputs requested from the model.

Application state never depends on parsing Markdown: every model call that drives execution returns
one of these Pydantic models (JSON Schema sent to the inference server, validated on return).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from nova.domain.enums import IntentKind, SkillCategory, StepStatus


class IntentClassification(BaseModel):
    kind: IntentKind
    goal: str = Field(description="One-sentence restatement of what the user wants to achieve")
    category: SkillCategory | None = None
    artifact_type: str | None = Field(default=None, description="Artifact type the user expects, if any")
    target_artifact_id: str | None = Field(default=None, description="Only an id listed in AVAILABLE ARTIFACTS")
    target_sections: list[str] = Field(default_factory=list, description="Section keys to change or explain")
    target_item_id: str | None = Field(default=None, description="Item id the user refers to, if any")
    needs_context: bool = True
    context_query: str = Field(default="", description="What to look for in the project context")
    candidate_skill_ids: list[str] = Field(default_factory=list, max_length=8)
    response_language: str = Field(default="en", description="ISO code of the user's language")


class ContextRequest(BaseModel):
    project_slug: str
    query: str
    purpose: str = "general"
    token_budget: int = 4000


class PlannedStep(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_-]+$")
    title: str
    skill_id: str
    rationale: str = ""


class MissingInput(BaseModel):
    key: str
    question: str
    skill_id: str | None = None


class PlanOutput(BaseModel):
    """What the planner model returns (validated then turned into an ``ExecutionPlan``)."""

    objective: str
    steps: list[PlannedStep] = Field(min_length=1, max_length=8)
    missing_inputs: list[MissingInput] = Field(default_factory=list, max_length=5)
    assumptions: list[str] = Field(default_factory=list, max_length=8)


class ExecutionStep(BaseModel):
    id: str
    title: str
    skill_id: str | None
    skill_version: str | None = None
    status: StepStatus = StepStatus.pending
    rationale: str = ""
    detail: str = ""
    artifact_id: str | None = None


class ExecutionPlan(BaseModel):
    objective: str
    steps: list[ExecutionStep]
    requires_user_input: bool = False
    missing_inputs: list[MissingInput] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confirmed: bool = False
    workflow_id: str | None = None

    def step(self, step_id: str) -> ExecutionStep | None:
        return next((s for s in self.steps if s.id == step_id), None)

    def next_pending(self) -> ExecutionStep | None:
        return next((s for s in self.steps if s.status in (StepStatus.pending, StepStatus.running)), None)

    @property
    def done_count(self) -> int:
        return sum(1 for s in self.steps if s.status in (StepStatus.completed, StepStatus.skipped))


class ToolRequest(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class ToolResult(BaseModel):
    tool: str
    status: Literal["ok", "error", "denied", "waiting_approval"]
    output: Any = None
    error: str | None = None


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    model_calls: int = 0

    def add(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            model_calls=self.model_calls + other.model_calls,
        )


class AnswerOutput(BaseModel):
    answer: str = Field(description="Concise answer. Cite context as [S1] only when used.")
    citations: list[str] = Field(default_factory=list, description="Labels of the context items used")
    follow_ups: list[str] = Field(default_factory=list, max_length=3)


class ArtifactUpdate(BaseModel):
    artifact_id: str
    sections: list[str]
    summary: str = ""


class EvaluationReference(BaseModel):
    system: Literal["forge"] = "forge"
    scenario_id: str | None = None
    run_id: str | None = None
    status: str | None = None
    composite_score: float | None = None
    passed: bool | None = None
    url: str | None = None


class TaskStatusView(BaseModel):
    task_id: str
    status: str
    phase: str
    done: int
    total: int
