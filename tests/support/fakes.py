"""Test doubles for the LLM, ORBIT and FORGE ports (tests only — never used by production code)."""

from __future__ import annotations

import itertools
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import BaseModel

from nova.domain.context import (
    ContextBundle,
    ContextChange,
    ContextError,
    ContextIdentity,
    ContextItem,
    ContextOverview,
    ContextProjectInfo,
    ContextQuery,
    SearchResult,
)
from nova.domain.evaluation import ExecutionRecord, FeedbackRecord
from nova.domain.llm import LLMMessage, LLMResult, StructuredResult
from nova.domain.outputs import (
    AnswerOutput,
    EvaluationReference,
    IntentClassification,
    PlanOutput,
    TokenUsage,
)
from tests.support.schema_faker import fake

Handler = Callable[[list[LLMMessage]], Any]


class ScriptedLLM:
    """Deterministic LLM: per-schema handlers; Skill steps are generated from the JSON Schema."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[LLMMessage]]] = []
        self.intent: Handler = lambda m: IntentClassification(kind="run_workflow", goal="Write a PRD", context_query="product")
        self.plan: Handler = lambda m: PlanOutput(
            objective="Write the PRD", steps=[{"id": "1-prd", "title": "Write the PRD", "skill_id": "prd"}]
        )
        self.answer: Handler = lambda m: AnswerOutput(answer="Answer based on [S1].", citations=["S1"])
        self.step_citations = ["S1", "S99"]  # S99 does not exist → must be dropped
        self.step_override: Callable[[dict, list[LLMMessage]], dict] | None = None
        self.fail_times = 0

    @property
    def model_name(self) -> str:
        return "test-model"

    async def generate(self, messages: list[LLMMessage], **_: Any) -> LLMResult:
        return LLMResult(text="ok", model="test-model", usage=TokenUsage(input_tokens=10, output_tokens=5, model_calls=1))

    async def stream(self, messages: list[LLMMessage], **_: Any) -> AsyncIterator[str]:
        yield "ok"

    async def structured_output(
        self, messages: list[LLMMessage], schema: type[BaseModel], *, json_schema: dict | None = None, **_: Any
    ) -> StructuredResult:
        from nova.domain.llm import LLMError

        self.calls.append((schema.__name__, messages))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise LLMError("temporarily unavailable", retryable=True)
        name = schema.__name__
        if name == "IntentClassification":
            value = self.intent(messages)
        elif name == "PlanOutput":
            value = self.plan(messages)
        elif name == "AnswerOutput":
            value = self.answer(messages)
        else:
            assert json_schema is not None
            raw = fake(json_schema, citations=self.step_citations)
            if self.step_override:
                raw = self.step_override(raw, messages)
            Draft202012Validator(json_schema).validate(raw)
            value = schema.model_validate(raw)
        if isinstance(value, dict):
            value = schema.model_validate(value)
        return StructuredResult(
            value=value, model="test-model", usage=TokenUsage(input_tokens=100, output_tokens=50, model_calls=1)
        )


def context_item(
    n: int, title: str, *, classification: int = 1, excerpt: str = "", memory_kind: str | None = None
) -> ContextItem:
    return ContextItem(
        citation=f"S{n}",
        ref_id=f"chunk-{n}",
        kind="memory" if memory_kind else "document",
        title=title,
        excerpt=excerpt or f"Excerpt of {title}",
        memory_kind=memory_kind,
        source_kind=None if memory_kind else "document",
        document_id=None if memory_kind else f"00000000-0000-0000-0000-00000000000{n}",
        classification=classification,
        date=datetime(2026, 9, 20, tzinfo=UTC),
        relevance=0.8,
        project_slug="forge",
        source_system="orbit",
    )


class FakeContextProvider:
    def __init__(self, items: list[ContextItem] | None = None) -> None:
        self.items = items or [context_item(1, "FORGE Vision v2", memory_kind="decision"), context_item(2, "Q4 Objectives")]
        self.error: ContextError | None = None
        self.queries: list[ContextQuery] = []
        self.feedback: list[tuple[str, bool]] = []
        self.changes: list[ContextChange] = []
        self.proposals: list[dict] = []
        self._ids = itertools.count(1)

    async def retrieve(self, query: ContextQuery) -> ContextBundle:
        self.queries.append(query)
        if self.error:
            raise self.error
        return ContextBundle(
            retrieval_id=f"orbit-req-{next(self._ids)}",
            project_slug=query.project_slug,
            items=list(self.items),
            warnings=[],
            excluded_count=2,
        )

    async def list_projects(self, user_id: str) -> list[ContextProjectInfo]:
        return [ContextProjectInfo(slug="forge", name="FORGE", description="AI Evaluation Platform", role="owner")]

    async def recent_changes(self, user_id: str, project_slug: str, since: datetime | None) -> list[ContextChange]:
        return [c for c in self.changes if c.project_slug == project_slug]

    async def overview(self, user_id: str, project_slug: str) -> ContextOverview:
        return ContextOverview(project_slug=project_slug, documents=12, memory_items=6, decisions=3, sources=2, snapshots=1)

    async def search(self, user_id: str, project_slug: str, query: str, limit: int = 10) -> list[SearchResult]:
        return [SearchResult(ref_id="chunk-1", project_slug=project_slug, title="FORGE Vision v2", snippet="…")]

    async def send_feedback(self, user_id: str, project_slug: str, retrieval_id: str, useful: bool, comment: str | None) -> None:
        self.feedback.append((retrieval_id, useful))

    async def identity(self, user_id: str) -> ContextIdentity:
        return ContextIdentity(linked=True, external_user_id="orbit-user", email="y@example.com", mode="session")

    async def propose_memory(self, user_id: str, project_slug: str, **kwargs: Any) -> str:
        self.proposals.append(kwargs)
        return "memory-1"

    async def publish_document(self, user_id: str, project_slug: str, **kwargs: Any) -> str:
        self.proposals.append(kwargs)
        return "document-1"


class FakeEvaluationSink:
    def __init__(self) -> None:
        self.captured: list[ExecutionRecord] = []
        self.feedbacks: list[FeedbackRecord] = []

    async def capture(self, record: ExecutionRecord) -> EvaluationReference | None:
        self.captured.append(record)
        return EvaluationReference(scenario_id="scenario-1", run_id="run-1", status="pending")

    async def refresh(self, reference: EvaluationReference) -> EvaluationReference:
        return reference.model_copy(update={"status": "completed", "composite_score": 82.0, "passed": True})

    async def feedback(self, reference: EvaluationReference, feedback: FeedbackRecord) -> None:
        self.feedbacks.append(feedback)
