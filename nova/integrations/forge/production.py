"""Production executions → FORGE observed runs (``NOVA_FORGE_CAPTURE_MODE=observed``).

The default capture re-executes the request inside FORGE, under whichever version is active *then*: its score
says nothing about the release the user actually got. An observed run reports what really happened — outcome,
skills, tokens, the run manifest (agent version, snapshot, policies, release) — and is scored by deterministic
rules on a small structured result, so releases can be compared on real traffic. Neither the answer nor the context
is ever sent. The user's request is sent (redacted of personal data) only with ``NOVA_FORGE_CAPTURE_INTENT=true``;
by default FORGE sees which Skills ran, not what was asked.
"""

from __future__ import annotations

from typing import Any

from nova.domain.evaluation import ExecutionRecord
from nova.infra.redaction import redact_obj

SCENARIO_SLUG = "nova-production-run"
CONFIG_KEY = "nova-production"
MAX_EVENTS = 100


def scenario_body() -> dict[str, Any]:
    """The one scenario every observed production run is attached to (rules on ``output_json``)."""

    def expected(rule_id: str, path: str, value: Any, criterion: str, severity: str, text: str) -> dict[str, Any]:
        return {
            "id": rule_id,
            "type": "expected_value",
            "params": {"path": path, "value": value},
            "criterion_key": criterion,
            "severity": severity,
            "description": text,
        }

    return {
        "slug": SCENARIO_SLUG,
        "name": "NOVA — exécution de production (run observé)",
        "category": "production",
        "visibility": "public",
        "classification": 1,
        "tags": ["nova", "observed", "production"],
        "changelog": "Version initiale : notation par règles sur output_json.",
        "content": {
            "description": (
                "Exécution réelle d'une demande par NOVA (compétences, validation, livrables). Évaluée à partir de runs "
                "observés : la note vient des règles ci-dessous appliquées à output_json."
            ),
            "difficulty": "medium",
            "input": {"prompt": "Traiter une demande utilisateur de bout en bout avec les compétences NOVA."},
            "expected_behavior": "L'exécution se termine (outcome=completed), toutes les compétences aboutissent et aucune erreur n'est levée.",
            "criteria": [
                {"key": "quality.completed", "name": "Terminé", "weight": 3, "question": "L'exécution s'est-elle terminée ?"},
                {
                    "key": "quality.skills_completed",
                    "name": "Compétences abouties",
                    "weight": 2,
                    "question": "Toutes les compétences ont-elles produit leur résultat ?",
                },
                {"key": "quality.clean", "name": "Sans erreur", "weight": 1, "question": "Aucune erreur n'a-t-elle été levée ?"},
            ],
            "rules": [
                expected("completed", "outcome", "completed", "quality.completed", "high", "outcome vaut « completed »"),
                expected(
                    "skills_completed",
                    "all_skills_completed",
                    True,
                    "quality.skills_completed",
                    "high",
                    "toutes les compétences ont abouti",
                ),
                expected("clean", "error_count", 0, "quality.clean", "low", "aucune erreur levée"),
            ],
        },
    }


def evaluation_config_body() -> dict[str, Any]:
    """Rules only, no LLM judge; an execution that did not complete is capped so it can never pass."""
    return {
        "key": CONFIG_KEY,
        "name": "NOVA — production (règles uniquement)",
        "description": "Notation déterministe des exécutions de production NOVA : règles du scénario sur output_json.",
        "dimension_weights": {"quality": 1.0},
        "pass_threshold": 70,
        "gates": [
            {
                "id": "must-complete",
                "kind": "rule",
                "target": "completed",
                "action": "cap",
                "cap": 50,
                "description": "Une exécution qui n'a pas abouti ne peut pas dépasser 50 (donc ne peut pas réussir).",
            }
        ],
    }


def observed_output(record: ExecutionRecord) -> dict[str, Any]:
    """The structured result FORGE's rules read: what happened, never what was said."""
    return {
        "outcome": "completed" if record.status == "completed" else "failed",
        "all_skills_completed": all(s.status == "completed" for s in record.skills),
        "error_count": len(record.errors),
        "skills": [{"skill_id": s.skill_id, "version": s.version, "status": s.status} for s in record.skills],
        "artifact_count": len(record.artifact_ids),
        "tools": record.tools,
        "context_items": len(record.context_documents),
        "context_max_classification": record.context_max_classification,
    }


def _prompt(record: ExecutionRecord, include_intent: bool) -> str:
    """What FORGE shows as the request: the user's words only when the organization opted in (redacted), else the Skills."""
    if include_intent:
        return str(redact_obj(record.user_intent[:2000]))
    skills = ", ".join(s.skill_id for s in record.skills) or "none"
    return f"[request text not sent] Skills: {skills}"


def _events(record: ExecutionRecord) -> list[dict[str, Any]]:
    """Steps as Agent Protocol events: one per skill (with its duration), one per tool used."""
    events: list[dict[str, Any]] = []
    offset = 0.0
    for skill in record.skills:
        duration = float(skill.duration_ms or 0.0)
        events.append(
            {
                "type": "custom",
                "name": f"Compétence {skill.skill_id} v{skill.version}",
                "offset_ms": offset,
                "duration_ms": duration,
                "status": "ok" if skill.status == "completed" else "error",
                "attributes": {"skill_id": skill.skill_id, "skill_version": skill.version, "step": skill.step_id},
            }
        )
        offset += duration
    for tool in record.tools:
        events.append({"type": "tool_call", "name": tool, "offset_ms": offset, "attributes": {"tool": tool}})
    return events[:MAX_EVENTS]


def observed_run_body(
    record: ExecutionRecord,
    *,
    agent_version_id: str,
    scenario_id: str,
    evaluation_config_id: str | None = None,
    include_intent: bool = False,
) -> dict[str, Any]:
    """``POST /runs/observed`` body (FORGE docs/OBSERVED_RUNS.md): real outcome, usage, manifest and steps."""
    output = observed_output(record)
    started = record.started_at or record.finished_at
    finished = record.finished_at or record.started_at
    tags = ["nova", "nova-production", f"nova-task:{record.task_id}", *[f"skill:{s.skill_id}@{s.version}" for s in record.skills]]
    release = (record.manifest or {}).get("release_id")
    if release:
        tags.append(f"release:{release}")
    body: dict[str, Any] = {
        "agent_version_id": agent_version_id,
        "scenario_id": scenario_id,
        "evaluation_config_id": evaluation_config_id,
        "external_id": f"nova-task:{record.task_id}",
        "input": {"prompt": _prompt(record, include_intent), "context": {}},
        "output_text": f"{output['outcome']}: {len(record.skills)} compétence(s), {len(record.artifact_ids)} livrable(s)",
        "output_json": output,
        "execution_status": output["outcome"],
        "error": redact_obj("; ".join(record.errors)[:1000]) if record.errors and output["outcome"] == "failed" else None,
        "started_at": started.isoformat() if started else None,
        "completed_at": finished.isoformat() if finished else None,
        "usage": {
            "input_tokens": record.usage.input_tokens,
            "output_tokens": record.usage.output_tokens,
            "model_calls": record.usage.model_calls,
        },
        "tags": tags[:20],
        "events": _events(record),
    }
    if record.manifest:
        body["manifest"] = record.manifest
    return body
