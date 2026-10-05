"""Typed structured outputs requested from the model.

Application state never depends on parsing Markdown: every model call that drives execution returns
one of these Pydantic models (JSON Schema sent to the inference server, validated on return).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

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
    response_language: str = Field(default="en", description="ISO 639-1 code of the user's language (en, fr…)")

    @field_validator("response_language", mode="before")
    @classmethod
    def _iso_language(cls, value: object) -> str:
        """Models sometimes answer "French" or "fr-FR": keep the two-letter code."""
        text = str(value or "en").strip().lower()
        names = {"french": "fr", "français": "fr", "francais": "fr", "english": "en", "anglais": "en"}
        return names.get(text, text[:2] if len(text) >= 2 else "en")


class ContextRequest(BaseModel):
    project_slug: str
    query: str
    purpose: str = "general"
    token_budget: int = 4000


class PlannedStep(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_-]+$")
    title: str
    skill_id: str
    goal: str = Field(default="", description="What this step must deliver toward the user's goal, one sentence")
    rationale: str = Field(default="", description="Why this step and its Skill are needed, one sentence")


class PlannedMilestone(BaseModel):
    title: str = Field(description="Short operational title, in the user's language")
    kind: Literal["skill", "human"] = Field(
        description="skill: NOVA produces it with a Skill; human: a decision or action only the team can take"
    )
    skill_id: str | None = Field(default=None, description="Only for kind=skill: a skill id from CANDIDATE SKILLS")
    goal: str = Field(default="", description="What this milestone delivers toward the goal, one sentence")
    rationale: str = Field(default="", description="Why it is needed at this point, one sentence")


class GoalPlanOutput(BaseModel):
    """NOVA's plan for a Goal: ordered milestones toward the expected result."""

    summary: str = Field(description="How NOVA will reach the goal, two sentences, in the user's language")
    milestones: list[PlannedMilestone] = Field(min_length=2, max_length=10)
    assumptions: list[str] = Field(default_factory=list, max_length=5)


class LearnedStep(BaseModel):
    title: str = Field(description="Short operational title, in the user's language")
    instruction: str = Field(description="What to do at this step, generalised (no one-off names or dates)")
    skill_id: str | None = Field(default=None, description="A skill id from CANDIDATE SKILLS when a Skill does this step")


class LearnedSkillDraft(BaseModel):
    """A reusable workflow NOVA generalised from what it observed the user do (Teach NOVA)."""

    name: str = Field(description="Name of the workflow, 2 to 5 words, in the user's language")
    description: str = Field(description="One sentence: what it achieves and when to use it")
    steps: list[LearnedStep] = Field(min_length=2, max_length=12)
    routine_suggestion: str = Field(default="", description="When it could run as a routine, if relevant (e.g. 'Every Friday')")


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
    goal: str = ""  # sub-objective set by NOVA when it decomposes the task
    started_at: str | None = None  # ISO timestamps: the sub-agent's working time shown live
    finished_at: str | None = None
    validation: dict[str, Any] | None = None  # StepValidation from NOVA's Validation agent
    handoff: dict[str, Any] | None = None  # note passed to the next sub-agent {to, title, note}


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
