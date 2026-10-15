"""Three separate indicators of a NOVA run (never one number that hides which one is low).

* **Execution health**: did the run complete, did every Skill deliver, were there errors. The rule score FORGE computes on
  observed runs (``integrations/forge/production.py``); a run that finished but produced something useless still scores 100.
* **Deliverable quality**: is what was delivered usable: content present, validation passed, citations kept, user rating.
* **Business gain**: was the deliverable accepted, and how much did people have to correct it.

Deliverable quality and business gain only use signals NOVA really has; a signal that is missing is left out of the score
(never counted as good or bad), and with no signal at all there is no score. No LLM judge is involved: qualitative
evaluation of an output would only be allowed on declassified output (see ``integrations/forge/guard.py``).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

HEALTH_WEIGHTS = {"completed": 3, "skills_completed": 2, "clean": 1}  # the weights of FORGE's production criteria
VALIDATION_VALUE = {"passed": 1.0, "revised": 0.7, "warning": 0.0}  # a step fixed after a revision counts less than a clean one


class ScoreCheck(BaseModel):
    key: str
    weight: int
    value: float  # 0..1
    detail: str = ""


class Score(BaseModel):
    score: float | None  # 0..100, ``None`` when no signal is available
    checks: list[ScoreCheck] = Field(default_factory=list)


def _weighted(checks: list[ScoreCheck]) -> Score:
    total = sum(c.weight for c in checks)
    return Score(score=round(100 * sum(c.weight * c.value for c in checks) / total, 1) if total else None, checks=checks)


def execution_health(*, completed: bool, all_skills_completed: bool, error_count: int) -> int:
    earned = (
        (HEALTH_WEIGHTS["completed"] if completed else 0)
        + (HEALTH_WEIGHTS["skills_completed"] if all_skills_completed else 0)
        + (HEALTH_WEIGHTS["clean"] if error_count == 0 else 0)
    )
    return round(100 * earned / sum(HEALTH_WEIGHTS.values()))


class DeliverableSignals(BaseModel):
    artifacts: int = 0
    sections: int = 0  # sections the Artifact types define, over all delivered Artifacts
    empty_sections: int | None = None
    validation: list[str] = Field(default_factory=list)  # per step: passed | revised | warning
    dropped_citations: int | None = None  # citations NOVA removed because no served source backed them
    useful: bool | None = None  # the user's rating


def deliverable_quality(signals: DeliverableSignals) -> Score:
    checks: list[ScoreCheck] = []
    if signals.artifacts == 0:
        checks.append(ScoreCheck(key="has_content", weight=3, value=0.0, detail="No deliverable was produced"))
    else:
        filled = 1.0
        if signals.empty_sections is not None and signals.sections:
            filled = 1 - min(signals.empty_sections, signals.sections) / signals.sections
        detail = f"{signals.empty_sections} empty section(s)" if signals.empty_sections else "All sections drafted"
        checks.append(ScoreCheck(key="has_content", weight=3, value=filled, detail=detail))
    if signals.validation:
        value = sum(VALIDATION_VALUE.get(v, 0.0) for v in signals.validation) / len(signals.validation)
        checks.append(ScoreCheck(key="validated", weight=3, value=value, detail=", ".join(signals.validation)))
    if signals.dropped_citations is not None:
        n = signals.dropped_citations
        checks.append(
            ScoreCheck(
                key="citations_resolved",
                weight=2,
                value=1.0 if n == 0 else 0.0,
                detail="Every citation matches a source" if n == 0 else f"{n} unverifiable citation(s) removed",
            )
        )
    if signals.useful is not None:
        checks.append(ScoreCheck(key="user_feedback", weight=2, value=1.0 if signals.useful else 0.0, detail="User rating"))
    return _weighted(checks)


class BusinessSignals(BaseModel):
    accepted: bool | None = None  # the deliverable was kept (final / in review / rated useful) or refused
    versions: int = 0  # versions of the delivered Artifacts
    human_versions: int = 0  # of which written by people (corrections)


def business_gain(signals: BusinessSignals) -> Score:
    checks: list[ScoreCheck] = []
    if signals.accepted is not None:
        checks.append(
            ScoreCheck(key="accepted", weight=3, value=1.0 if signals.accepted else 0.0, detail="Deliverable accepted"
                       if signals.accepted else "Deliverable refused")
        )  # fmt: skip
        if signals.accepted and signals.versions:  # corrections only qualify a deliverable that was kept
            rate = min(signals.human_versions, signals.versions) / signals.versions
            checks.append(
                ScoreCheck(key="corrections", weight=2, value=1 - rate, detail=f"{round(100 * rate)}% corrected by people")
            )
    return _weighted(checks)
