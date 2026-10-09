"""Evaluation of SDLC runs: how often NOVA delivers, how much repair it needs, what a run costs.

Computed from the run rows themselves (stage outputs, log, usage): nothing is stored twice. FORGE cannot ingest observed
production runs yet (docs/integration-analysis.md, gap G-F1), so these figures stay in NOVA and are exportable as JSON.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from nova.infra.db import aware
from nova.infra.models import SdlcRun

FINISHED = ("completed", "failed", "cancelled")


def _stage(run: SdlcRun, key: str) -> dict[str, Any]:
    return next((s for s in (run.stages or []) if s["key"] == key), {})


def _seconds(start: datetime | None, end: datetime | None) -> int | None:
    start, end = aware(start), aware(end)
    return int((end - start).total_seconds()) if start and end and end >= start else None


def run_evaluation(run: SdlcRun) -> dict[str, Any]:
    """Quality and cost signals of one run."""
    usage = run.usage or {}
    context = run.context or {}
    review = _stage(run, "review").get("output") or {}
    rounds = review.get("rounds") or []
    ci = _stage(run, "ci")
    ci_state = (ci.get("output") or {}).get("state") if ci.get("status") in ("done", "skipped") else None
    failed_stage = next((s["key"] for s in (run.stages or []) if s["status"] == "failed"), None)
    log = run.log or []
    tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
    ci_fixes = int(context.get("ci_fix_rounds", 0))
    return {
        "outcome": run.status,
        "merged": bool(run.merge_sha),
        "failed_stage": failed_stage if run.status == "failed" else None,
        "reached_ci": ci.get("status") in ("done", "skipped", "failed"),  # a red CI that stopped the run counts
        "ci_state": ci_state,
        "ci_fix_rounds": ci_fixes,
        "first_pass_ci": ci_state == "success" and ci_fixes == 0,
        "review_rounds": len(rounds),
        "review_fix_rounds": max(len(rounds) - 1, 0),
        "blocking_findings": sum(1 for f in (rounds[0]["findings"] if rounds else []) if f["severity"] in ("blocker", "major")),
        "human_interventions": sum(1 for e in log if e["message"].startswith("Approved:") or e["message"] == "Retry requested"),
        "retries": sum(1 for e in log if e["message"] == "Retry requested"),
        "duration_seconds": _seconds(run.created_at, run.finished_at),
        "model_calls": int(usage.get("model_calls", 0)),
        "tokens": tokens,
        "input_tokens": int(usage.get("input_tokens", 0)),
        "output_tokens": int(usage.get("output_tokens", 0)),
        "model": run.model,
    }


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def _avg(values: list[float | int]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def aggregate(runs: list[SdlcRun]) -> dict[str, Any]:
    """Success rate, CI repairs and cost per run over ``runs`` (review runs are counted apart: they write nothing)."""
    delivery = [r for r in runs if r.kind != "review"]
    evals = [(r, run_evaluation(r)) for r in delivery]
    finished = [(r, e) for r, e in evals if r.status in FINISHED]
    completed = [(r, e) for r, e in finished if r.status == "completed"]
    failed = [(r, e) for r, e in finished if r.status == "failed"]
    reached_ci = [(r, e) for r, e in evals if e["reached_ci"]]
    by_model: dict[str, dict[str, Any]] = {}
    for model in {e["model"] for _, e in evals if e["model"]}:
        mine = [(r, e) for r, e in evals if e["model"] == model]
        done = [x for x in mine if x[0].status in FINISHED]
        by_model[model] = {
            "runs": len(mine),
            "success_rate": _rate(sum(1 for r, _ in done if r.status == "completed"), len(done)),
            "avg_tokens": _avg([e["tokens"] for _, e in mine]),
        }
    return {
        "runs": len(runs),
        "delivery_runs": len(delivery),
        "review_runs": len(runs) - len(delivery),
        "active": sum(1 for r in delivery if r.status not in FINISHED),
        "completed": len(completed),
        "failed": len(failed),
        "cancelled": len(finished) - len(completed) - len(failed),
        # Of the runs that ended on their own (cancelled ones are the user's choice and excluded)
        "success_rate": _rate(len(completed), len(completed) + len(failed)),
        "merged_rate": _rate(sum(1 for _, e in finished if e["merged"]), len(finished)),
        "first_pass_ci_rate": _rate(sum(1 for _, e in reached_ci if e["first_pass_ci"]), len(reached_ci)),
        "avg_ci_fix_rounds": _avg([e["ci_fix_rounds"] for _, e in reached_ci]),
        "avg_review_fix_rounds": _avg([e["review_fix_rounds"] for _, e in evals if e["review_rounds"]]),
        "avg_human_interventions": _avg([e["human_interventions"] for _, e in finished]),
        "avg_tokens": _avg([e["tokens"] for _, e in evals if e["tokens"]]),
        "avg_model_calls": _avg([e["model_calls"] for _, e in evals if e["model_calls"]]),
        "total_tokens": sum(e["tokens"] for _, e in evals),
        "avg_duration_seconds": _avg([e["duration_seconds"] for _, e in completed if e["duration_seconds"] is not None]),
        "failures_by_stage": dict(Counter(e["failed_stage"] for _, e in failed if e["failed_stage"])),
        "by_model": by_model,
    }
