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
