"""SDLC Autopilot runs → FORGE observed runs.

NOVA sends what is needed to evaluate the delivery — outcome, CI/review repairs, interventions, tokens, stage summaries —
and never code or diffs (repository content may be classified C2/C3). Free text is redacted first.
"""

from __future__ import annotations

from typing import Any

from nova.infra.db import aware
from nova.infra.models import SdlcRun
from nova.infra.redaction import redact_obj
from nova.services.sdlc_metrics import run_evaluation

AGENT_SLUG = "nova-sdlc"
SCENARIO_SLUG = "nova-sdlc-delivery"
SUMMARY_CHARS = 400


def agent_body() -> dict[str, Any]:
    return {
        "name": "NOVA · SDLC Autopilot",
        "slug": AGENT_SLUG,
        "description": "NOVA's autonomous software delivery (spec → PR → CI → merge). Runs are ingested as observed runs.",
        "provider": "ORION · NOVA",
        "tags": ["nova", "orion", "sdlc"],
        "metadata": {"managed_by": "nova", "observed": True},
    }


def agent_version_body(*, nova_version: str, model: str, endpoint: str) -> dict[str, Any]:
    """One immutable FORGE agent version per NOVA release × model (the model is the user's own)."""
    return {
        "version": f"{nova_version}+{model}"[:40],
        "adapter_kind": "nova",
        "endpoint": endpoint,
        "model": {"provider": "external", "model": model or "unknown"},
        "orchestration_config": {"runtime": "sdlc-autopilot", "observed": True},
        "context_config": {"source": "repository"},
        "metadata": {"nova_version": nova_version, "observed": True},
        "changelog": f"NOVA {nova_version} SDLC Autopilot — model {model}",
    }


CONFIG_KEY = "nova-delivery"

_CRITERIA = [
    ("quality.delivered", "Livré", 3, "Le run s'est-il terminé avec outcome = completed ?"),
    ("quality.merged", "Fusionné", 3, "Le changement a-t-il été fusionné ?"),
    ("quality.ci_first_pass", "CI verte du premier coup", 2, "La CI est-elle passée sans correction ?"),
    ("quality.no_review_fixes_needed", "Revue sans correction", 1, "La revue s'est-elle terminée sans tour de correction ?"),
    ("ux.autonomy", "Autonomie", 1, "L'agent a-t-il eu besoin d'au plus 2 interventions humaines ?"),
]


def scenario_body() -> dict[str, Any]:
    """The FORGE scenario every SDLC run is attached to: rule-scored on ``output_json`` (contract: FORGE docs/OBSERVED_RUNS.md §3.1)."""

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
        "name": "NOVA — livraison SDLC (run observé)",
        "category": "software_delivery",
        "visibility": "public",
        "classification": 1,
        "tags": ["nova", "observed"],
        "changelog": "Version initiale : notation par règles sur output_json.",
        "content": {
            "description": (
                "Livraison d'un changement par le pipeline SDLC de NOVA (spécification, code, CI, revue, fusion). Scénario évalué à "
                "partir de runs observés : la note vient des règles ci-dessous appliquées à output_json."
            ),
            "difficulty": "medium",
            "input": {"prompt": "Livrer un changement de bout en bout via le pipeline SDLC NOVA."},
            "expected_behavior": (
                "Le changement est livré (outcome=completed) et fusionné, la CI passe du premier coup, la revue ne demande aucune "
                "correction et l'agent a besoin d'au plus 2 interventions humaines."
            ),
            "criteria": [{"key": k, "name": n, "weight": w, "question": q} for k, n, w, q in _CRITERIA],
            "rules": [
                expected("delivered", "outcome", "completed", "quality.delivered", "high", "outcome vaut « completed »"),
                expected("merged", "merged", True, "quality.merged", "high", "merged vaut true"),
                expected("ci_first_pass", "first_pass_ci", True, "quality.ci_first_pass", "low", "first_pass_ci vaut true"),
                expected(
                    "no_review_fixes_needed",
                    "review_fix_rounds",
                    0,
                    "quality.no_review_fixes_needed",
                    "low",
                    "review_fix_rounds vaut 0",
                ),
                {
                    "id": "autonomy",
                    "type": "json_schema",
                    "params": {
                        "schema": {
                            "type": "object",
                            "required": ["human_interventions"],
                            "properties": {"human_interventions": {"type": "integer", "maximum": 2}},
                        }
                    },
                    "criterion_key": "ux.autonomy",
                    "severity": "low",
                    "error_type": "INSTRUCTION_FAILURE",
                    "description": "human_interventions ≤ 2",
                },
            ],
        },
    }


def evaluation_config_body() -> dict[str, Any]:
    """Rules only, no LLM judge; an unmerged change is capped at 60 so it can never pass (FORGE docs/OBSERVED_RUNS.md §3.2)."""
    return {
        "key": CONFIG_KEY,
        "name": "NOVA — livraison (règles uniquement)",
        "description": "Notation déterministe des runs observés NOVA : règles du scénario sur output_json, aucun juge LLM.",
        "dimension_weights": {"quality": 0.8, "ux": 0.2},
        "pass_threshold": 70,
        "gates": [
            {
                "id": "must-be-merged",
                "kind": "rule",
                "target": "merged",
                "action": "cap",
                "cap": 60,
                "description": "Un changement non fusionné ne peut pas dépasser 60 (donc ne peut pas réussir).",
            }
        ],
    }


def observed_output(run: SdlcRun) -> dict[str, Any]:
    """The structured result FORGE's rules read: delivery metrics plus stage summaries (no code)."""
    evaluation = run_evaluation(run)
    return redact_obj(
        {
            "outcome": "completed" if run.status == "completed" else "failed",
            "kind": run.kind,
            "autonomy": run.autonomy,
            "auto_merge": run.auto_merge,
            **{k: v for k, v in evaluation.items() if k not in ("outcome", "model")},
            "model": run.model,
            "stages": [
                {"key": s["key"], "status": s["status"], "summary": (s.get("summary") or "")[:SUMMARY_CHARS]}
                for s in (run.stages or [])
            ],
        }
    )


def observed_run_body(
    run: SdlcRun, *, agent_version_id: str, scenario_id: str, evaluation_config_id: str | None = None
) -> dict[str, Any]:
    output = observed_output(run)
    usage = run.usage or {}
    lines = [f"- {s['key']}: {s['status']}" + (f" — {s['summary']}" if s["summary"] else "") for s in output["stages"]]
    return {
        "agent_version_id": agent_version_id,
        "scenario_id": scenario_id,
        "evaluation_config_id": evaluation_config_id,
        "external_id": f"nova-sdlc:{run.id}",
        "input": redact_obj(
            {"prompt": f"[{run.kind}] {run.title}\n{(run.goal or '')[:2000]}".strip(), "context": {"repository": run.repo}}
        ),
        "output_text": redact_obj(f"{run.title}\n" + "\n".join(lines)),
        "output_json": output,
        "execution_status": output["outcome"],
        "error": redact_obj(run.error[:1000]) if run.error else None,
        "started_at": aware(run.created_at).isoformat() if run.created_at else None,
        "completed_at": aware(run.finished_at).isoformat() if run.finished_at else None,
        "usage": {
            "input_tokens": int(usage.get("input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
            "model_calls": int(usage.get("model_calls", 0)),
        },
        "tags": ["nova", "nova-sdlc", f"kind:{run.kind}", f"autonomy:{run.autonomy}", f"model:{run.model or 'unknown'}"][:20],
    }
