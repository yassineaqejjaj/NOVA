"""Releases: how a candidate policy reaches everyone — canary, health check, approval, rollback.

Pure rules (no I/O). A candidate FORGE validated is first exposed to a small, *stable* share of users (the
same user always gets the same version, so a person never flips between behaviours). Its executions are
compared with everyone else's over the same period; a clear degradation rolls it back automatically, a
healthy canary waits for a human (or goes live when the organization chose no approval).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel


class ReleaseStatus(StrEnum):
    canary = "canary"  # exposed to a share of users, being compared
    awaiting_approval = "awaiting_approval"  # healthy canary, waiting for an administrator
    active = "active"  # applied to everyone
    rolled_back = "rolled_back"  # withdrawn (automatically or by an administrator)
    rejected = "rejected"  # never reached everyone: refused at approval
    superseded = "superseded"  # was active, replaced by a newer release


OPEN_STATUSES = (ReleaseStatus.canary, ReleaseStatus.awaiting_approval)

#: Executions that count as production traffic (replays and FORGE evaluation calls never do).
TRAFFIC_ORIGINS = ("interactive", "scheduled", "goal", "routine")


def bucket(release_id: str, user_id: str) -> int:
    """Stable 0-99 position of a user for a release (same user, same release → same bucket)."""
    digest = hashlib.sha256(f"{release_id}:{user_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


def in_canary(release_id: str, user_id: str, percent: int) -> bool:
    return bucket(release_id, user_id) < max(0, min(100, percent))


@dataclass(frozen=True)
class Cohort:
    runs: int  # executions that reached a final state
    failed: int

    @property
    def failure_rate(self) -> float:
        return self.failed / self.runs if self.runs else 0.0


class CanaryVerdict(BaseModel):
    outcome: str  # waiting | healthy | degraded
    reason: str
    canary_failure_rate: float
    control_failure_rate: float


def canary_verdict(canary: Cohort, control: Cohort, *, min_runs: int, max_increase: float) -> CanaryVerdict:
    """Compare the canary with the control: ``waiting`` until enough runs, then ``healthy`` or ``degraded``."""
    base = {"canary_failure_rate": round(canary.failure_rate, 4), "control_failure_rate": round(control.failure_rate, 4)}
    if canary.runs < min_runs:
        return CanaryVerdict(outcome="waiting", reason=f"{canary.runs}/{min_runs} exécutions observées.", **base)
    increase = canary.failure_rate - control.failure_rate
    if increase > max_increase:
        return CanaryVerdict(
            outcome="degraded",
            reason=(
                f"Échecs {canary.failure_rate:.0%} avec la nouvelle version contre {control.failure_rate:.0%} "
                f"pour les autres (seuil : +{max_increase:.0%})."
            ),
            **base,
        )
    return CanaryVerdict(
        outcome="healthy",
        reason=f"Échecs {canary.failure_rate:.0%} contre {control.failure_rate:.0%} : pas de dégradation.",
        **base,
    )
