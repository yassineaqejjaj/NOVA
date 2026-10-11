"""Dynamic team assembly: choosing agents, Skills and tools from what is known about the mission.

* **Measured performance** (FORGE): between Skills that fit a request about equally well, the one FORGE scored
  better on its evaluation cases is preferred. The adjustment is deliberately small — a tie-breaker, never a way
  to replace a Skill that matches the request, and never applied to a Skill the user named.
* **Mission constraints** (ORBIT): when the context served for the mission includes C3 (secret) material, tools
  that write to an external system are withheld from every step.
* **The team** is recorded on the plan: which specialist agents carry the work, with which Skills and what FORGE
  measured for them, so the choice can be read, replayed and compared.

Pure functions, no I/O.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from pydantic import BaseModel, Field

REFERENCE_SCORE = 70.0  # FORGE composite (0-100) that neither helps nor hurts
MAX_BONUS = 1.5  # router score points a Skill can gain or lose (matches span tens of points)
SENSITIVE_CLASSIFICATION = 3


def performance_bonus(score: float | None) -> float:
    """Router score adjustment for a Skill FORGE measured at ``score`` (none when it was never measured)."""
    if score is None:
        return 0.0
    return max(-MAX_BONUS, min(MAX_BONUS, (score - REFERENCE_SCORE) / 20.0))


def withholds_external_writes(max_classification: int) -> bool:
    """Secret (C3) context never travels with a tool that writes to an external system."""
    return max_classification >= SENSITIVE_CLASSIFICATION


class TeamMember(BaseModel):
    agent: str
    skills: list[str] = Field(default_factory=list)
    score: float | None = None  # mean FORGE score of the Skills it carries here, when measured


def build_team(steps: Iterable[tuple[str, str]], scores: Mapping[str, float]) -> list[TeamMember]:
    """The specialist agents of a plan, in order of first appearance: ``steps`` are ``(skill_id, agent)``."""
    members: dict[str, TeamMember] = {}
    for skill_id, agent in steps:
        member = members.setdefault(agent, TeamMember(agent=agent))
        if skill_id not in member.skills:
            member.skills.append(skill_id)
    for member in members.values():
        known = [scores[s] for s in member.skills if s in scores]
        member.score = round(sum(known) / len(known), 1) if known else None
    return list(members.values())


# --- Sufficiency-aware assembly ------------------------------------------------------------------------------------

DISCOVERY = "discovery"


def discovery_step(
    candidates: Iterable[tuple[str, str]], planned: Iterable[str], sufficiency: str | None, steps_left: int
) -> str | None:
    """The Skill to put first when ORBIT says the context cannot support the work (``None``: nothing to add).

    ``candidates`` are ``(skill_id, category)`` best first, already ranked against the request: only a discovery
    Skill that *fits the request* is considered, and never when one is already planned or the plan is full.
    """
    if sufficiency != "insufficient" or steps_left <= 0:
        return None
    planned = set(planned)
    discovery = [s for s, category in candidates if category == DISCOVERY]
    if not discovery or planned & set(discovery):
        return None
    return discovery[0]


# --- Compositions that worked before ---------------------------------------------------------------------------------

MIN_COMPOSITION_RUNS = 5  # runs of the same composition before its record counts
MIN_COMPOSITION_SUCCESS = 0.8
MAX_COMPOSITION_BONUS = 1.0


def composition_bonuses(history: Iterable[tuple[tuple[str, ...], bool]]) -> dict[str, float]:
    """Router bonus per Skill from how compositions fared on requests of the same category.

    ``history`` is ``(skills in order, succeeded)`` for past executions. The best composition with enough runs and
    a high success rate lends a small bonus to each of its Skills, so a proven combination is favoured when
    candidates are otherwise close. Never decisive (<= ``MAX_COMPOSITION_BONUS``), never negative: a composition
    that failed is simply not encouraged.
    """
    runs: dict[tuple[str, ...], list[bool]] = {}
    for skills, ok in history:
        if skills:
            runs.setdefault(skills, []).append(ok)
    proven = [
        (sum(v) / len(v), len(v), skills)
        for skills, v in runs.items()
        if len(v) >= MIN_COMPOSITION_RUNS and sum(v) / len(v) >= MIN_COMPOSITION_SUCCESS
    ]
    if not proven:
        return {}
    rate, _, best = max(proven)
    bonus = (
        round(MAX_COMPOSITION_BONUS * (rate - MIN_COMPOSITION_SUCCESS) / (1 - MIN_COMPOSITION_SUCCESS), 3)
        if rate < 1
        else MAX_COMPOSITION_BONUS
    )
    return dict.fromkeys(best, max(0.1, bonus))
