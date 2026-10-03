"""Evaluation port: what NOVA hands to an evaluation platform (implemented by the FORGE adapter).

NOVA does not score itself; it describes executions and forwards feedback.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from nova.domain.outputs import EvaluationReference, TokenUsage


class SkillUse(BaseModel):
    skill_id: str
    version: str
    step_id: str
    status: str
    duration_ms: float | None = None


class ExecutionRecord(BaseModel):
    """Everything an evaluator needs to understand one NOVA execution (no raw reasoning)."""

    task_id: str
    trace_id: str | None
    user_intent: str
    origin: str
    agent_version: str
    model: str | None
    workflow: list[str] = Field(default_factory=list)  # skill ids in order
    skills: list[SkillUse] = Field(default_factory=list)
    context_retrieval_ids: list[str] = Field(default_factory=list)
    context_documents: list[dict[str, Any]] = Field(default_factory=list)  # {id, title, content, source}
    context_max_classification: int = 0
    tools: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    artifact_type: str | None = None
    output_markdown: str = ""
    usage: TokenUsage = Field(default_factory=TokenUsage)
    status: str
    errors: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class FeedbackRecord(BaseModel):
    rating: Literal["useful", "not_useful"]
    comment: str | None = None
    task_id: str | None = None
    artifact_id: str | None = None
    skill_id: str | None = None
    skill_version: str | None = None


class EvaluationSink(Protocol):
    async def capture(self, record: ExecutionRecord) -> EvaluationReference | None: ...

    async def refresh(self, reference: EvaluationReference) -> EvaluationReference: ...

    async def feedback(self, reference: EvaluationReference, feedback: FeedbackRecord) -> None: ...
