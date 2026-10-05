"""What NOVA's specialist agents learned from FORGE (training loop, docs/TRAINING.md).

An agent's *policy* is a versioned set of lessons distilled from FORGE feedback reports:

* ``standards`` — lessons that apply to every Skill of the agent (added to its professional standards);
* ``skills`` — lessons for one Skill (added to the Skill's instructions and checked by the Validation agent).

A policy is only applied after a FORGE experiment (baseline vs candidate) showed it does not regress, so the
prompts stay the source of truth and every change is reversible. This module is pure: no I/O.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from pydantic import BaseModel, Field

from nova.domain.agents import AgentProfile

#: FORGE recommendation categories a prompt lesson can address. The others (retrieval, tools, model,
#: orchestration, memory) need a change in NOVA itself: they are kept as recommendations for the team.
PROMPT_CATEGORIES = frozenset({"system_prompt", "output_format", "rule", "context"})
LESSON_PRIORITIES = frozenset({"p0", "p1"})
MAX_SKILL_LESSONS = 5
MAX_AGENT_STANDARDS = 6
MAX_LESSON_CHARS = 300
#: A lesson found in this many Skills of the same agent becomes one of the agent's standards.
PROMOTE_TO_STANDARD_MIN_SKILLS = 3


class AgentLearning(BaseModel):
    """The lessons of one agent's policy, as applied to an execution (snapshotted in ``NovaState.learning``)."""

    policy_id: str | None = None
    version: int = 0
    standards: list[str] = Field(default_factory=list)
    skills: dict[str, list[str]] = Field(default_factory=dict)


def learning_of(snapshot: dict[str, Any] | None, profile: AgentProfile | str) -> AgentLearning | None:
    raw = (snapshot or {}).get(str(profile))
    return AgentLearning.model_validate(raw) if raw else None


def standards_lines(snapshot: dict[str, Any] | None, profile: AgentProfile | str) -> list[str]:
    learning = learning_of(snapshot, profile)
    return list(learning.standards) if learning else []


def skill_lessons(snapshot: dict[str, Any] | None, profile: AgentProfile | str, skill_id: str) -> list[str]:
    learning = learning_of(snapshot, profile)
    return list(learning.skills.get(skill_id, [])) if learning else []


# --- Distillation ---------------------------------------------------------------------------------


class SkillFeedback(BaseModel):
    """The FORGE evaluation of one Skill (a training scenario) for the baseline policy."""

    skill_id: str
    score: float | None = None  # FORGE composite score (0 to 100), mean over repetitions
    weaknesses: list[str] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)  # FORGE FeedbackRecommendation
    report_id: str | None = None


class Distillation(BaseModel):
    standards: list[str]
    skills: dict[str, list[str]]
    other_recommendations: list[dict[str, Any]]  # non-prompt recommendations, for the team
    changed_skills: list[str]
    report_ids: list[str]
    new_standards: list[str] = Field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.changed_skills) or bool(self.new_standards)


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= MAX_LESSON_CHARS else text[: MAX_LESSON_CHARS - 1].rstrip() + "…"


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9à-ÿ]+", " ", text.lower()).strip()


def lesson_from_recommendation(rec: dict[str, Any]) -> str | None:
    """A FORGE recommendation → one imperative lesson (title + description), or ``None`` when not a prompt lesson.

    Evidence excerpts are never copied: lessons must not carry scenario content (classification safety).
    """
    if rec.get("category") not in PROMPT_CATEGORIES or rec.get("priority", "p1") not in LESSON_PRIORITIES:
        return None
    title = _clean(str(rec.get("title") or ""))
    description = _clean(str(rec.get("description") or ""))
    if not title and not description:
        return None
    if not description or _key(description).startswith(_key(title)):
        return _clean(description or title)
    return _clean(f"{title.rstrip('.')}: {description}")


def _merge(new: list[str], existing: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for lesson in [*new, *existing]:
        key = _key(lesson)
        if key and key not in seen:
            seen.add(key)
            merged.append(lesson)
    return merged[:limit]


def distill(
    feedback: list[SkillFeedback],
    current: AgentLearning | None,
    *,
    rewritten: dict[str, list[str]] | None = None,
) -> Distillation:
    """Merge the lessons drawn from FORGE feedback into the current policy (deterministic).

    ``rewritten`` optionally replaces the lessons of a Skill by a model-condensed version of them (same intent,
    fewer words); the merge, the limits and the promotion to agent standards stay deterministic.
    """
    current = current or AgentLearning()
    per_skill: dict[str, list[str]] = {}
    others: list[dict[str, Any]] = []
    for item in feedback:
        lessons: list[str] = []
        for rec in item.recommendations:
            lesson = lesson_from_recommendation(rec)
            if lesson:
                lessons.append(lesson)
            elif rec.get("category") not in PROMPT_CATEGORIES:
                others.append(
                    {
                        "skill_id": item.skill_id,
                        "category": rec.get("category"),
                        "priority": rec.get("priority"),
                        "title": _clean(str(rec.get("title") or "")),
                        "description": _clean(str(rec.get("description") or "")),
                    }
                )
        if rewritten and rewritten.get(item.skill_id):
            lessons = [_clean(text) for text in rewritten[item.skill_id] if text.strip()]
        if lessons:
            per_skill[item.skill_id] = _merge(lessons, [], MAX_SKILL_LESSONS)

    # A lesson learned on several Skills belongs to the agent, not to each Skill.
    counts = Counter(_key(lesson) for lessons in per_skill.values() for lesson in set(lessons))
    shared_keys = {key for key, n in counts.items() if n >= PROMOTE_TO_STANDARD_MIN_SKILLS}
    shared = []
    for lessons in per_skill.values():
        for lesson in lessons:
            if _key(lesson) in shared_keys and _key(lesson) not in {_key(s) for s in shared}:
                shared.append(lesson)
    existing_standard_keys = {_key(s) for s in current.standards}
    new_standards = [s for s in shared if _key(s) not in existing_standard_keys]
    standards = _merge(new_standards, current.standards, MAX_AGENT_STANDARDS)
    standard_keys = {_key(s) for s in standards}

    skills = {k: list(v) for k, v in current.skills.items()}
    changed: list[str] = []
    for skill_id, lessons in per_skill.items():
        specific = [lesson for lesson in lessons if _key(lesson) not in standard_keys]
        before = skills.get(skill_id, [])
        after = _merge(specific, [x for x in before if _key(x) not in standard_keys], MAX_SKILL_LESSONS)
        if after != before:
            changed.append(skill_id)
        if after:
            skills[skill_id] = after
        else:
            skills.pop(skill_id, None)
    return Distillation(
        standards=standards,
        skills=skills,
        other_recommendations=others[:50],
        changed_skills=sorted(changed),
        new_standards=new_standards,
        report_ids=[f.report_id for f in feedback if f.report_id],
    )


# --- Promotion ------------------------------------------------------------------------------------


class PromotionDecision(BaseModel):
    promote: bool
    reason: str


def promotion_decision(comparison: dict[str, Any]) -> PromotionDecision:
    """Automatic promotion rule on a finished FORGE experiment comparison (baseline = active, candidate = new).

    * ``ship`` → promoted;
    * ``ship_with_caution`` → promoted only when the composite score improves and no scenario regresses critically;
    * anything else (``inconclusive``, ``do_not_ship``) → rejected, the active policy stays.
    """
    rec = (comparison.get("recommendation") or {}).get("recommendation")
    composite = comparison.get("composite") or {}
    delta = composite.get("delta")
    critical = [r for r in comparison.get("regressions") or [] if r.get("severity") == "critical"]
    if rec == "ship":
        return PromotionDecision(promote=True, reason="FORGE recommande la version candidate.")
    if rec == "ship_with_caution":
        if critical:
            return PromotionDecision(promote=False, reason=f"{len(critical)} régression(s) critique(s) détectée(s).")
        if not isinstance(delta, int | float) or delta <= 0:
            return PromotionDecision(promote=False, reason="Aucun gain mesuré sur le score composite.")
        return PromotionDecision(promote=True, reason="Gain mesuré sans régression critique.")
    if rec == "do_not_ship":
        return PromotionDecision(promote=False, reason="FORGE a détecté une régression.")
    if rec == "inconclusive":
        return PromotionDecision(promote=False, reason="Résultat non concluant : la version active est conservée.")
    return PromotionDecision(promote=False, reason="Aucune recommandation FORGE.")
