"""NOVA ↔ FORGE mapping (the only module that knows FORGE payload shapes besides the client/schemas)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from nova.domain import training_pack
from nova.domain.agents import AGENTS, AgentProfile, agent_instructions
from nova.domain.context import ContextItem
from nova.domain.evaluation import ExecutionRecord
from nova.domain.skills import SkillSpec
from nova.integrations.forge.schemas import FapEvent, NovaRunRequest

AGENT_SLUG = "nova"
NOVA_AGENT_ID = "nova-orchestrator"
SCENARIO_CATEGORY = "nova-production"
USEFULNESS_CRITERION = "ux.perceived_usefulness"
TRAINING_CATEGORY = "nova-training"
TRAINING_TAG = "nova-training"


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
        # C2/C3 context stays private in FORGE (only maintainers see private scenario content)
        "visibility": "private" if record.context_max_classification >= 2 else "public",
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


# --- Training loop (docs/TRAINING.md) --------------------------------------------------------------


def specialist_agent_id(profile: AgentProfile | str) -> str:
    """NOVA Agent Protocol id of one specialist evaluated alone (``nova-product``…)."""
    return f"nova-{AgentProfile(profile).value}"


def profile_of(nova_agent_id: str) -> AgentProfile | None:
    """``nova-product`` → product; ``nova-orchestrator`` (and unknown ids) → ``None``."""
    suffix = nova_agent_id.removeprefix("nova-")
    return AgentProfile(suffix) if suffix in AgentProfile.__members__ and nova_agent_id.startswith("nova-") else None


def training_agent_body(profile: AgentProfile) -> dict[str, Any]:
    spec = AGENTS[profile]
    return {
        "name": f"NOVA · {spec.name}",
        "slug": specialist_agent_id(profile),
        "description": f"NOVA's {spec.name}, evaluated alone on each of its Skills ({spec.mission}).",
        "provider": "ORION · NOVA",
        "tags": ["nova", "orion", TRAINING_TAG, f"agent:{profile.value}"],
        "metadata": {"managed_by": "nova", "agent": profile.value},
    }


def training_version_body(
    *,
    profile: AgentProfile,
    policy_id: str,
    policy_version: int,
    standards: list[str],
    lessons: dict[str, list[str]],
    skills: list[SkillSpec],
    catalog_digest: str,
    nova_version: str,
    model: str,
    nova_base_url: str,
    credential_id: str | None,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    """One FORGE agent version per policy of the agent (the policy id makes the content hash unique)."""
    agent_id = specialist_agent_id(profile)
    body: dict[str, Any] = {
        "version": "",  # set below from the content fingerprint
        "adapter_kind": "nova",
        "endpoint": nova_base_url,
        "adapter_config": {"nova_agent_id": agent_id, "nova_options": {"policy_id": policy_id}},
        "model": {"provider": "vllm", "model": model},
        # Informational: what the agent is told (persona + learned standards); Skill lessons are in metadata.
        "system_prompt": agent_instructions(profile, standards),
        "orchestration_config": {"runtime": "langgraph", "agent": agent_id, "policy_version": policy_version},
        "context_config": {"source": "scenario"},
        "budget": {"timeout_seconds": timeout_seconds, "max_steps": 8},
        "metadata": {
            "nova_version": nova_version,
            "agent": profile.value,
            "policy_id": policy_id,
            "policy_version": policy_version,
            "skill_catalog": catalog_digest,
            "skills": {s.id: s.version for s in skills},
            "lessons": {k: len(v) for k, v in lessons.items()},
        },
        "changelog": f"NOVA {nova_version} — {AGENTS[profile].name} — policy v{policy_version}",
    }
    if credential_id:
        body["credential_id"] = credential_id
    body["version"] = f"{policy_version}.{version_key(body)[:8]}"  # FORGE shows it as « v3.1a2b3c4d »
    return body


def version_key(body: dict[str, Any]) -> str:
    """Fingerprint of an agent version body (without its label): equal keys = same FORGE version."""
    content = {k: v for k, v in body.items() if k not in ("version", "changelog")}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]


def training_scenario_slug(skill: SkillSpec) -> str:
    """Stable per Skill version × training pack: a changed Skill gets a new scenario (comparable cycles)."""
    digest = hashlib.sha256(f"{skill.content_hash}|{training_pack.PACK_VERSION}".encode()).hexdigest()[:8]
    return f"nova-train-{skill.id}-{digest}"[:120]


def training_scenario_body(skill: SkillSpec) -> dict[str, Any]:
    """The service scenario of one Skill: synthetic C1 project, the Skill forced, the Skill's own criteria and checks."""
    prompt = (
        f"{skill.summary}\n\nProject: {training_pack.PROJECT}. Use the project context provided and cite it; "
        "state your assumptions and open questions instead of inventing facts."
    )
    criteria = [
        {k: v for k, v in c.items() if k in ("key", "question", "weight", "rubric")}
        for c in skill.evaluation.criteria
        if c.get("key")
    ]
    rules = [
        {"type": check.type, "params": check.params, **({"description": check.description} if check.description else {})}
        for check in skill.evaluation.checks
    ]
    return {
        "slug": training_scenario_slug(skill),
        "name": f"NOVA · {skill.name} (training)",
        "category": TRAINING_CATEGORY,
        "visibility": "public",
        "classification": training_pack.PACK_CLASSIFICATION,
        "tags": [TRAINING_TAG, f"agent:{skill.agent.value}", f"skill:{skill.id}@{skill.version}"],
        "changelog": f"NOVA training scenario for {skill.id}@{skill.version} (pack {training_pack.PACK_VERSION})",
        "content": {
            "description": f"Service scenario of the Skill {skill.name} ({AGENTS[skill.agent].name}): {skill.purpose}".strip()[
                :20000
            ],
            # `nova_skill` is passed through by FORGE to the NOVA Agent Protocol: the Skill is forced.
            "input": {"prompt": prompt, "nova_skill": skill.id},
            "context": {"documents": training_pack.DOCUMENTS},
            "constraints": [],
            "expected_behavior": training_pack.EXPECTED_BEHAVIOR,
            **({"criteria": criteria} if criteria else {}),
            **({"rules": rules} if rules else {}),
        },
    }


def training_runs_body(agent_version_id: str, scenario_ids: list[str], repetitions: int, cycle_id: str) -> dict[str, Any]:
    return {
        "agent_version_id": agent_version_id,
        "scenario_ids": scenario_ids,
        "repetitions": repetitions,
        "tags": [TRAINING_TAG, f"training-cycle:{cycle_id}"],
    }


def training_experiment_body(
    *,
    profile: AgentProfile,
    cycle_id: str,
    baseline_version_id: str,
    candidate_version_id: str,
    scenario_ids: list[str],
    repetitions: int,
    candidate_version: int,
    changed_skills: list[str],
    source_feedback_report_id: str | None,
) -> dict[str, Any]:
    name = AGENTS[profile].name
    body: dict[str, Any] = {
        "name": f"NOVA · {name} · policy v{candidate_version}"[:200],
        "description": f"Training cycle {cycle_id}: lessons learned on {len(changed_skills)} Skill(s).",
        "hypothesis": "The lessons distilled from FORGE feedback improve the agent without regression on its other Skills.",
        "baseline_version_id": baseline_version_id,
        "candidate_version_id": candidate_version_id,
        "scenario_ids": scenario_ids,
        "repetitions": repetitions,
        "tags": [TRAINING_TAG, f"training-cycle:{cycle_id}", f"agent:{profile.value}"],
        "trigger": "nova-training",
    }
    if source_feedback_report_id:
        body["source_feedback_report_id"] = source_feedback_report_id
    return body
