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
SCENARIO_CATEGORY = "nova-sdlc"
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


def scenario_body() -> dict[str, Any]:
    """The FORGE scenario every SDLC run is attached to (rule-scored from ``output_json``; see docs/ENGINEERING.md)."""
    return {
        "name": "NOVA · SDLC delivery",
        "slug": SCENARIO_SLUG,
        "category": SCENARIO_CATEGORY,
        "visibility": "public",
        "classification": 1,
        "tags": ["nova", "sdlc"],
        "changelog": "Observed runs of NOVA's SDLC Autopilot",
        "content": {
            "description": "A change delivered end to end by NOVA: specification, code, tests, pull request, review, CI, merge.",
            "input": {"prompt": "Deliver the requested change on the user's repository."},
            "context": {"documents": []},
            "constraints": [],
            "expected_behavior": "The change is delivered, merged, with CI green first time and little human intervention.",
        },
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


def observed_run_body(run: SdlcRun, *, agent_version_id: str, scenario_id: str) -> dict[str, Any]:
    output = observed_output(run)
    usage = run.usage or {}
    lines = [f"- {s['key']}: {s['status']}" + (f" — {s['summary']}" if s["summary"] else "") for s in output["stages"]]
    return {
        "agent_version_id": agent_version_id,
        "scenario_id": scenario_id,
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
