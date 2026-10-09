"""Mirrors of the ORBIT payloads NOVA consumes (ORBIT `app/schemas/*`, `app/features/*`).

Responses use ``extra="ignore"`` so ORBIT can add fields; requests are built explicitly because
ORBIT input models use ``extra="forbid"`` (integration-analysis §1.2).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(extra="ignore")


class OrbitUser(_Out):
    id: str
    email: str
    full_name: str = ""
    is_admin: bool = False
    clearance: int = 1


class OrbitScores(_Out):
    final: float = 0.0


class OrbitContextItem(_Out):
    citation: str
    candidate_type: str  # chunk | memory | session
    id: str
    document_id: str | None = None
    memory_item_id: str | None = None
    title: str
    source_kind: str | None = None
    memory_kind: str | None = None
    memory_scope: str | None = None
    uri: str | None = None
    version: int | None = None
    excerpt: str = ""
    tokens: int = 0
    scores: OrbitScores = Field(default_factory=OrbitScores)
    classification: int = 1
    date: datetime | None = None
    pii_redacted: bool = False
    reason_code: str = ""
    reason_detail: str = ""


class OrbitContextPackage(_Out):
    request_id: str
    trace_id: str | None = None
    task: str = ""
    intent: str = "general"
    context: str = ""
    items: list[OrbitContextItem] = Field(default_factory=list)
    exclusion_summary: dict[str, int] = Field(default_factory=dict)
    tokens_used: int = 0
    token_budget: int = 0
    candidates_count: int = 0
    timings: dict[str, Any] = Field(default_factory=dict)  # ORBIT adds structured entries (e.g. per-round details)
    warnings: list[str] = Field(default_factory=list)


class OrbitProjectStats(_Out):
    sources: int = 0
    documents: int = 0
    memory_items: int = 0
    context_requests_7d: int = 0


class OrbitProject(_Out):
    id: str
    slug: str
    name: str
    description: str = ""
    role: str | None = None
    stats: OrbitProjectStats | None = None


class OrbitChangeEvent(_Out):
    id: str
    project_id: str
    type: str
    type_label: str = ""
    title: str
    summary: str = ""
    target_type: str = ""
    target_id: str | None = None
    classification: int = 1
    actor_label: str = ""
    created_at: datetime
    data: dict[str, Any] = Field(default_factory=dict)


class OrbitPage(_Out):
    items: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0


class OrbitSearchHit(_Out):
    chunk_id: str
    document_id: str
    document_title: str
    source_kind: str | None = None
    text: str = ""
    score: float = 0.0
    section: str | None = None
    source_updated_at: datetime | None = None


class OrbitMemoryItem(_Out):
    id: str
    title: str
    status: str = "proposed"
