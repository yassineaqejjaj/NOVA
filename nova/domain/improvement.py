"""How the system improves over time: score curve per agent, changes that were stopped, failure-rate trend.

Pure rules (no I/O). The service feeds in what NOVA already stores (policies, cycles, releases, executions);
nothing here is invented: an agent with no FORGE score has an empty curve, not a flat one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

#: A policy counts on the curve once it reached users (it is active or was before being replaced).
LIVE_STATUSES = ("active", "retired")
#: Releases that ended without reaching everyone.
STOPPED_RELEASES = ("rolled_back", "rejected")


@dataclass(frozen=True)
class PolicyPoint:
    version: int
    status: str
    score: float | None
    lessons: int
    standards: int
    at: datetime | None  # activation time, creation time when it never went live


@dataclass(frozen=True)
class CyclePoint:
    status: str
    baseline_version: int | None
    baseline_mean: float | None
    at: datetime


@dataclass(frozen=True)
class ReleasePoint:
    status: str
    label: str
    reason: str
    at: datetime | None


@dataclass(frozen=True)
class Traffic:
    runs: int
    failed: int

    @property
    def failure_rate(self) -> float | None:
        return round(self.failed / self.runs, 4) if self.runs else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def score_curve(policies: list[PolicyPoint], cycles: list[CyclePoint]) -> list[dict[str, Any]]:
    """Score of every version that reached users, oldest first, starting from the first measured baseline."""
    points: dict[int, dict[str, Any]] = {}
    measured = sorted((c for c in cycles if c.baseline_mean is not None), key=lambda c: c.at)
    if measured:
        first = measured[0]
        version = first.baseline_version if first.baseline_version is not None else 0
        points[version] = {"version": version, "score": round(first.baseline_mean, 1), "at": _iso(first.at), "baseline": True}
    for policy in sorted(policies, key=lambda p: p.version):
        if policy.status not in LIVE_STATUSES or policy.score is None:
            continue
        points[policy.version] = {
            "version": policy.version,
            "score": round(policy.score, 1),
            "at": _iso(policy.at),
            "lessons": policy.lessons,
            "standards": policy.standards,
            "baseline": False,
        }
    return [points[v] for v in sorted(points)]


def agent_progress(policies: list[PolicyPoint], cycles: list[CyclePoint], releases: list[ReleasePoint]) -> dict[str, Any]:
    curve = score_curve(policies, cycles)
    gain = round(curve[-1]["score"] - curve[0]["score"], 1) if len(curve) >= 2 else None
    active = next((p for p in policies if p.status == "active"), None)
    stopped = [r for r in releases if r.status in STOPPED_RELEASES]
    return {
        "curve": curve,
        "start_score": curve[0]["score"] if curve else None,
        "current_score": curve[-1]["score"] if curve else None,
        "gain": gain,
        "active_version": active.version if active else None,
        "lessons": (active.lessons + active.standards) if active else 0,
        "versions_shipped": max(len(curve) - 1, 0),
        "changes_stopped": len([c for c in cycles if c.status == "rejected"]) + len(stopped),
        "rollbacks": len([r for r in releases if r.status == "rolled_back"]),
        "events": [
            {"kind": r.status, "label": r.label, "reason": r.reason, "at": _iso(r.at)}
            for r in sorted(releases, key=lambda r: r.at.timestamp() if r.at else 0, reverse=True)[:8]
        ],
    }


def traffic_trend(recent: Traffic, previous: Traffic, *, min_runs: int = 5) -> dict[str, Any]:
    """Failure rate of the last window against the one before; ``None`` until both hold enough runs to mean something."""
    enough = recent.runs >= min_runs and previous.runs >= min_runs
    change = None
    if enough and previous.failure_rate:
        change = round((recent.failure_rate - previous.failure_rate) / previous.failure_rate, 3)
    return {
        "recent": {"runs": recent.runs, "failure_rate": recent.failure_rate},
        "previous": {"runs": previous.runs, "failure_rate": previous.failure_rate},
        "relative_change": change,
        "comparable": enough,
    }


def headline(agents: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Totals across agents: the three numbers shown first."""
    gains = [a["gain"] for a in agents.values() if a["gain"] is not None]
    return {
        "mean_gain": round(sum(gains) / len(gains), 1) if gains else None,
        "versions_shipped": sum(a["versions_shipped"] for a in agents.values()),
        "lessons_learned": sum(a["lessons"] for a in agents.values()),
        "changes_stopped": sum(a["changes_stopped"] for a in agents.values()),
        "agents_measured": len(gains),
    }
