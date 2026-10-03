"""NOVA ↔ FORGE mapping (the only module that knows FORGE payload shapes besides the client/schemas)."""

from __future__ import annotations

from typing import Any

from nova.domain.context import ContextItem
from nova.domain.evaluation import ExecutionRecord
from nova.domain.skills import SkillSpec
from nova.integrations.forge.schemas import FapEvent, NovaRunRequest

AGENT_SLUG = "nova"
NOVA_AGENT_ID = "nova-orchestrator"
SCENARIO_CATEGORY = "nova-production"
USEFULNESS_CRITERION = "ux.perceived_usefulness"


def agent_body() -> dict[str, Any]:
    return {
        "name": "NOVA",
        "slug": AGENT_SLUG,
        "description": "Personal AI Product Agent (ORION). Evaluated through the NOVA Agent Protocol.",
        "provider": "ORION · NOVA",
        "tags": ["nova", "orion"],
        "metadata": {"managed_by": "nova"},
    }


def release_label(nova_version: str, model: str, catalog_digest: str) -> str:
    return f"{nova_version}+{catalog_digest[:8]}"[:40]


def agent_version_body(
    *, nova_version: str, model: str, catalog_digest: str, skills: list[SkillSpec], nova_base_url: str, credential_id: str | None
) -> dict[str, Any]:
    """Immutable FORGE agent version = NOVA release × model × Skill catalog (integration-analysis §2.7-2)."""
    body: dict[str, Any] = {
        "version": release_label(nova_version, model, catalog_digest),
        "adapter_kind": "nova",
        "endpoint": nova_base_url,
        "adapter_config": {"nova_agent_id": NOVA_AGENT_ID},
        "model": {"provider": "vllm", "model": model},
        "orchestration_config": {"runtime": "langgraph", "agent": NOVA_AGENT_ID},
        "context_config": {"source": "scenario"},
        "metadata": {
            "nova_version": nova_version,
            "skill_catalog": catalog_digest,
            "skills": {s.id: s.version for s in skills},
        },
        "changelog": f"NOVA {nova_version} — model {model} — skill catalog {catalog_digest}",
    }
    if credential_id:
        body["credential_id"] = credential_id
    return body


def scenario_body(record: ExecutionRecord) -> dict[str, Any]:
    """A production execution captured as a FORGE scenario (input + context served; no expected output)."""
    intent = record.user_intent.strip()
    skills = ", ".join(s.skill_id for s in record.skills) or "none"
    return {
        "name": f"NOVA · {intent[:120]}",
        "category": SCENARIO_CATEGORY,
        "visibility": "public",
        "classification": max(1, record.context_max_classification),
        "tags": ["nova", "production-capture", *[f"skill:{s.skill_id}@{s.version}" for s in record.skills]][:50],
        "changelog": f"Captured from NOVA task {record.task_id}",
        "content": {
            "description": f"Production request captured by NOVA (workflow: {skills}).",
            "input": {"prompt": intent},
            "context": {"documents": record.context_documents[:50]},
            "constraints": [],
            "expected_behavior": (
                "Produce the requested product Artifact, grounded in the provided context, citing sources, "
                "without inventing facts, metrics or decisions."
            ),
        },
    }


def run_body(agent_version_id: str, scenario_id: str, record: ExecutionRecord) -> dict[str, Any]:
    tags = ["nova", f"nova-task:{record.task_id}"] + [f"skill:{s.skill_id}@{s.version}" for s in record.skills]
    return {"agent_version_id": agent_version_id, "scenario_ids": [scenario_id], "repetitions": 1, "tags": tags[:20]}


def usefulness_evaluation(useful: bool, comment: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {"scores": [{"criterion_key": USEFULNESS_CRITERION, "score": 5 if useful else 1}]}
    if comment:
        body["scores"][0]["comment"] = comment[:5000]
        body["comment"] = comment[:10000]
    return body


def provided_context(request: NovaRunRequest) -> list[ContextItem]:
    """FORGE-prepared context → NOVA context items (reproducible evaluation, ORBIT is not called)."""
    items = []
    for i, doc in enumerate(request.context.documents, 1):
        items.append(
            ContextItem(
                citation=f"S{i}",
                ref_id=doc.id or f"doc-{i}",
                kind="document",
                title=doc.title or doc.id or f"Document {i}",
                excerpt=doc.content[:6000],
                source_system=doc.source or "forge",
            )
        )
    offset = len(items)
    for j, fact in enumerate(request.context.facts, 1):
        items.append(
            ContextItem(
                citation=f"S{offset + j}",
                ref_id=f"fact-{j}",
                kind="memory",
                memory_kind="fact",
                title=fact[:80],
                excerpt=fact,
                source_system="forge",
            )
        )
    return items


EVENT_TYPE = {"status": "decision", "progress": "custom", "block": "message", "task": "decision", "error": "error"}


def fap_events(events: list[dict[str, Any]]) -> list[FapEvent]:
    """Persisted NOVA execution events → FAP events (operational summaries only, never raw reasoning)."""
    result: list[FapEvent] = []
    for e in events:
        payload, created = e["payload"], e["created_at"]
        if e["type"] == "progress" and payload.get("status") in ("completed", "failed"):
            key = str(payload.get("key", ""))
            kind = "retrieval" if key == "context" else "decision" if key in ("intent", "plan") else "custom"
            result.append(
                FapEvent(
                    id=str(e["seq"]),
                    type=kind,
                    name=str(payload.get("label", key)),
                    ended_at=created,
                    status="error" if payload.get("status") == "failed" else "ok",
                    output=payload.get("detail") or None,
                    attributes={"nova.step": key},
                )
            )
        elif e["type"] == "block" and payload.get("block", {}).get("type") == "tool_execution":
            data = payload["block"]["data"]
            if data.get("status") in ("ok", "error", "denied"):
                result.append(
                    FapEvent(
                        id=str(e["seq"]),
                        type="tool_call",
                        name=str(data.get("tool")),
                        ended_at=created,
                        status="ok" if data.get("status") == "ok" else "error",
                        attributes={"tool": data.get("tool"), "error": data.get("error")},
                    )
                )
    return result
