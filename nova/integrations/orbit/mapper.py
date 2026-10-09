"""ORBIT payloads → NOVA domain (and NOVA requests → ORBIT payloads). The only place that knows both."""

from __future__ import annotations

from typing import Any

from nova.domain.context import (
    ContextBundle,
    ContextChange,
    ContextItem,
    ContextProjectInfo,
    ContextQuery,
    ContextSnapshot,
    ContextSnapshotInfo,
    ContextSnapshotItem,
    SearchResult,
    SnapshotRef,
)
from nova.integrations.orbit.schemas import (
    OrbitChangeEvent,
    OrbitContextPackage,
    OrbitProject,
    OrbitSearchHit,
    OrbitSnapshot,
    OrbitSnapshotListEntry,
)

KIND = {"chunk": "document", "memory": "memory", "session": "session"}


def context_request(query: ContextQuery, *, on_behalf_of: str | None) -> dict[str, Any]:
    """Body of ``POST /projects/{slug}/context`` (only fields declared by ORBIT's ContextRequestIn)."""
    body: dict[str, Any] = {
        "task": query.task,
        "intent": query.purpose,
        "token_budget": query.token_budget,
        "explain": False,  # NOVA only needs the served items; exclusion details stay in ORBIT
    }
    if query.source_kinds:
        body["source_kinds"] = query.source_kinds
    if query.max_classification is not None:
        body["max_classification"] = query.max_classification
    if query.session_id:
        body["session_id"] = query.session_id[:200]
    if query.base_snapshot:
        body["base_snapshot"] = {"name": query.base_snapshot.name}
        if query.base_snapshot.version is not None:
            body["base_snapshot"]["version"] = query.base_snapshot.version
    if on_behalf_of:
        body["on_behalf_of"] = on_behalf_of
    return body


def context_bundle(package: dict[str, Any], project_slug: str, orbit_public_url: str) -> ContextBundle:
    pkg = OrbitContextPackage.model_validate(package)
    items = []
    for raw in pkg.items:
        uri = raw.uri
        if not uri and raw.document_id:
            uri = f"{orbit_public_url.rstrip('/')}/projects/{project_slug}/sources/{raw.document_id}"
        elif not uri and raw.memory_item_id:
            uri = f"{orbit_public_url.rstrip('/')}/projects/{project_slug}/memory?item={raw.memory_item_id}"
        items.append(
            ContextItem(
                citation=raw.citation,
                ref_id=raw.id,
                kind=KIND.get(raw.candidate_type, "document"),  # type: ignore[arg-type]
                title=raw.title,
                excerpt=raw.excerpt,
                source_kind=raw.source_kind,
                memory_kind=raw.memory_kind,
                document_id=raw.document_id,
                memory_item_id=raw.memory_item_id,
                uri=uri,
                version=raw.version,
                classification=raw.classification,
                date=raw.date,
                relevance=raw.scores.final,
                pii_redacted=raw.pii_redacted,
                project_slug=project_slug,
                source_system="orbit",
            )
        )
    return ContextBundle(
        retrieval_id=pkg.request_id,
        trace_id=pkg.trace_id,
        project_slug=project_slug,
        items=items,
        warnings=pkg.warnings,
        excluded_count=sum(pkg.exclusion_summary.values()),
        candidates_count=pkg.candidates_count,
        tokens_used=pkg.tokens_used,
        snapshot=SnapshotRef(name=pkg.snapshot.name, version=pkg.snapshot.version) if pkg.snapshot else None,
        latency_ms=total if isinstance(total := pkg.timings.get("total"), int | float) else None,
    )


def project_info(raw: dict[str, Any]) -> ContextProjectInfo:
    p = OrbitProject.model_validate(raw)
    return ContextProjectInfo(
        slug=p.slug, name=p.name, description=p.description, role=p.role, stats=p.stats.model_dump() if p.stats else {}
    )


def change(raw: dict[str, Any], project_slug: str) -> ContextChange:
    e = OrbitChangeEvent.model_validate(raw)
    return ContextChange(
        id=e.id,
        project_slug=project_slug,
        type=e.type,
        type_label=e.type_label,
        title=e.title,
        summary=e.summary,
        target_type=e.target_type,
        target_id=e.target_id,
        classification=e.classification,
        created_at=e.created_at,
        data=e.data,
    )


def search_result(raw: dict[str, Any], project_slug: str) -> SearchResult:
    h = OrbitSearchHit.model_validate(raw)
    return SearchResult(
        ref_id=h.chunk_id,
        project_slug=project_slug,
        title=h.document_title,
        snippet=h.text[:500],
        source_kind=h.source_kind,
        document_id=h.document_id,
        score=h.score,
        updated_at=h.source_updated_at,
    )


MEMORY_KIND = {"decision", "requirement", "constraint", "fact", "risk"}


def memory_proposal(kind: str, title: str, content: str, source_label: str) -> dict[str, Any]:
    """``MemoryIn`` — always ``proposed`` (a human validates it in ORBIT)."""
    return {
        "scope": "project",
        "kind": kind if kind in MEMORY_KIND else "fact",
        "title": title[:300],
        "content": content[:8000],
        "status": "proposed",
        "tags": ["nova"],
        "provenance": [{"source_label": source_label[:200]}],
    }


def text_document(title: str, content: str, external_id: str, classification: int) -> dict[str, Any]:
    """``TextDocumentIn`` — Artifacts are published as ``document`` sources with their classification."""
    return {
        "source_kind": "document",
        "title": title[:300],
        "content": content,
        "external_id": external_id,
        "author": "NOVA",
        "classification": max(0, min(3, classification)),
        "tags": ["nova", "artifact"],
    }


def snapshot_info(raw: dict[str, Any]) -> ContextSnapshotInfo:
    e = OrbitSnapshotListEntry.model_validate(raw)
    return ContextSnapshotInfo(
        name=e.name,
        latest_version=e.latest_version,
        versions=e.versions,
        updated_at=e.updated_at,
        last_task=e.last_task or "",
    )


def snapshot(raw: dict[str, Any]) -> ContextSnapshot:
    s = OrbitSnapshot.model_validate(raw)
    return ContextSnapshot(
        name=s.name,
        version=s.version,
        task=s.task,
        intent=s.intent,
        token_count=s.token_count,
        content=s.content,
        items=[ContextSnapshotItem(**i.model_dump()) for i in s.items],
        created_by_label=s.created_by_label,
        created_at=s.created_at,
    )
