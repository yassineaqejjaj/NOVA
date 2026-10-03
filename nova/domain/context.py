"""Context port: what NOVA needs from a context platform (implemented by the ORBIT adapter).

The NOVA domain never sees ORBIT payloads — only these types.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field


class ContextQuery(BaseModel):
    """A request for governed context on behalf of a user."""

    user_id: str
    project_slug: str
    task: str = Field(min_length=1, max_length=8000)
    purpose: Literal["general", "specification", "design", "engineering", "research", "analysis", "validation"] = "general"
    token_budget: int = Field(default=4000, ge=500, le=32000)
    source_kinds: list[str] | None = None
    session_id: str | None = None
    max_classification: int | None = Field(default=None, ge=0, le=3)


class ContextItem(BaseModel):
    """One piece of context served to NOVA, with everything needed to cite it."""

    citation: str  # stable label within one retrieval, e.g. "S3"
    ref_id: str  # id of the context item at the source (chunk / memory id)
    kind: Literal["document", "memory", "session"] = "document"
    title: str
    excerpt: str
    source_kind: str | None = None  # document, ticket, crm, …
    memory_kind: str | None = None  # decision, requirement, …
    document_id: str | None = None
    memory_item_id: str | None = None
    uri: str | None = None
    version: int | None = None
    classification: int = 1
    date: datetime | None = None
    relevance: float | None = None
    pii_redacted: bool = False
    project_slug: str | None = None
    source_system: str = "orbit"
    flagged_injection: bool = False  # suspicious instructions detected inside the content
    reference_id: str | None = None  # NOVA context_retrieval_references.id that recorded this item


class ContextBundle(BaseModel):
    retrieval_id: str | None  # ORBIT request id
    trace_id: str | None = None
    project_slug: str | None = None
    items: list[ContextItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    excluded_count: int = 0
    candidates_count: int = 0
    tokens_used: int = 0
    latency_ms: float | None = None

    @property
    def max_classification(self) -> int:
        return max((item.classification for item in self.items), default=0)

    def by_citation(self) -> dict[str, ContextItem]:
        return {item.citation: item for item in self.items}


class ContextProjectInfo(BaseModel):
    slug: str
    name: str
    description: str = ""
    role: str | None = None
    stats: dict[str, int] = Field(default_factory=dict)


class ContextChange(BaseModel):
    """A change in the user's context (feeds Today recommendations)."""

    id: str
    project_slug: str
    type: str
    type_label: str = ""
    title: str
    summary: str = ""
    target_type: str = ""
    target_id: str | None = None
    classification: int = 1
    created_at: datetime
    data: dict = Field(default_factory=dict)


class SearchResult(BaseModel):
    ref_id: str
    project_slug: str
    title: str
    snippet: str
    source_kind: str | None = None
    document_id: str | None = None
    score: float = 0.0
    updated_at: datetime | None = None


class ContextIdentity(BaseModel):
    linked: bool
    external_user_id: str | None = None
    email: str | None = None
    display_name: str | None = None
    clearance: int | None = None
    expires_at: datetime | None = None
    mode: Literal["session", "agent_key", "none"] = "none"


class ContextError(Exception):
    """Context retrieval failure, translated for users (never a stack trace)."""

    def __init__(
        self,
        code: Literal["unauthorized", "forbidden", "not_found", "unavailable", "invalid", "not_linked"],
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class ContextProvider(Protocol):
    """Port implemented by ``nova.integrations.orbit.adapter.OrbitContextProvider``."""

    async def retrieve(self, query: ContextQuery) -> ContextBundle: ...

    async def list_projects(self, user_id: str) -> list[ContextProjectInfo]: ...

    async def recent_changes(self, user_id: str, project_slug: str, since: datetime | None) -> list[ContextChange]: ...

    async def search(self, user_id: str, project_slug: str, query: str, limit: int = 10) -> list[SearchResult]: ...

    async def send_feedback(
        self, user_id: str, project_slug: str, retrieval_id: str, useful: bool, comment: str | None
    ) -> None: ...

    async def identity(self, user_id: str) -> ContextIdentity: ...

    # Write-back (external writes: always behind the approval policy)
    async def propose_memory(
        self, user_id: str, project_slug: str, *, kind: str, title: str, content: str, source_label: str
    ) -> str: ...

    async def publish_document(
        self, user_id: str, project_slug: str, *, title: str, content: str, external_id: str, classification: int
    ) -> str: ...
