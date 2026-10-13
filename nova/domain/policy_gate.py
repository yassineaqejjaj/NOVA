"""Pre-activation proof of a learned policy: what FORGE must have shown before a candidate meets any user.

Pure rules (no I/O). A candidate (lessons distilled from low-scored runs) is compared with the active policy on a
validation set FORGE evaluated *outside production*. The set must be independent of what the lessons were made from,
big enough, show a minimal gain and no regression. The canary of ``domain/release.py`` stays the second line.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

GateMode = Literal["enforce", "warn", "off"]
Verdict = Literal["passed", "insufficient", "unavailable", "skipped"]


class Proof(BaseModel):
    """What FORGE measured for a candidate against its baseline (composite scores on a 0-1 scale)."""

    source: str  # e.g. "forge_experiment"
    validation_scenarios: list[str] = Field(default_factory=list)  # FORGE scenarios the comparison ran on
    lesson_scenarios: list[str] = Field(default_factory=list)  # scenarios (or runs) the lessons were made from
    runs_per_scenario: int = 1  # scored runs per scenario and arm
    gain: float | None = None  # candidate mean minus baseline mean
    regressions: list[str] = Field(default_factory=list)  # scenarios where the candidate is worse than the baseline


class GateDecision(BaseModel):
    verdict: Verdict
    reasons: list[str] = Field(default_factory=list)
    evaluations: int = 0  # independent scored runs per arm
    gain: float | None = None
    source: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict in ("passed", "skipped")


def decide(proof: Proof, *, min_gain: float, min_evaluations: int) -> GateDecision:
    """``passed`` only when every condition holds; each missing one is listed (the reason shown to the administrator)."""
    # Anti-contamination: a scenario the lessons come from proves nothing about them
    held_out = [s for s in dict.fromkeys(proof.validation_scenarios) if s not in set(proof.lesson_scenarios)]
    evaluations = len(held_out) * max(proof.runs_per_scenario, 1)
    reasons: list[str] = []
    if not held_out:
        reasons.append("aucun scénario de validation indépendant de ceux qui ont produit les leçons")
    elif evaluations < min_evaluations:
        reasons.append(f"{evaluations} évaluation(s) indépendante(s) sur {min_evaluations} requises")
    if proof.gain is None or proof.gain < min_gain:
        shown = "non mesuré" if proof.gain is None else f"{proof.gain:+.3f}"
        reasons.append(f"gain {shown} sous le minimum de {min_gain:+.3f}")
    if proof.regressions:
        reasons.append(f"régression sur {len(proof.regressions)} scénario(s) de garde : {', '.join(proof.regressions[:5])}")
    return GateDecision(
        verdict="insufficient" if reasons else "passed",
        reasons=reasons,
        evaluations=evaluations,
        gain=proof.gain,
        source=proof.source,
    )
