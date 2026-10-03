"""Deterministic Skill routing.

The router scores Skills against the intent (triggers, names, summaries, category, artifact type,
explicit references, user preferred methods) and returns a short candidate list. The model then
chooses **among candidates only**; any id outside the registry is rejected.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from nova.domain.enums import SkillCategory
from nova.domain.skills import SkillSpec
from nova.skills.registry import SkillRegistry

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "to",
    "for",
    "of",
    "in",
    "on",
    "my",
    "our",
    "this",
    "that",
    "me",
    "help",
    "please",
    "with",
    "i",
    "we",
    "want",
    "need",
    "create",
    "make",
    "it",
    "is",
    "be",
    "can",
    "you",
    "into",
    "from",
    "le",
    "la",
    "les",
    "de",
    "des",
    "du",
    "un",
    "une",
    "et",
    "pour",
    "mon",
    "ma",
    "mes",
    "je",
    "nous",
    "veux",
}


def _stem(word: str) -> str:
    """Light plural normalization (stories → story, requirements → requirement, metrics → metric)."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _tokens(text: str) -> set[str]:
    norm = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return {_stem(w) for w in _WORD.findall(norm) if w not in _STOP and len(w) > 1}


@dataclass(frozen=True)
class Candidate:
    skill: SkillSpec
    score: float
    reasons: tuple[str, ...]


class SkillRouter:
    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def candidates(
        self,
        intent: str,
        *,
        category: SkillCategory | None = None,
        artifact_type: str | None = None,
        explicit: list[str] | None = None,
        hinted: list[str] | None = None,
        preferred_methods: list[str] | None = None,
        limit: int = 8,
    ) -> list[Candidate]:
        words = _tokens(intent)
        text = intent.lower()
        scored: list[Candidate] = []
        explicit = [s for s in (explicit or []) if self.registry.has(s)]
        for skill in self.registry.all(include_system=False):
            score, reasons = 0.0, []
            if skill.id in explicit:
                score += 100
                reasons.append("explicitly referenced")
            for trigger in skill.triggers:
                if trigger.lower() in text:
                    score += 6
                    reasons.append(f"trigger '{trigger}'")
                    break
            overlap = words & _tokens(f"{skill.name} {skill.id.replace('-', ' ')}")
            if overlap:
                score += 3 * len(overlap)
                reasons.append("name match")
            summary_overlap = words & _tokens(f"{skill.summary} {' '.join(skill.triggers)}")
            score += 0.75 * len(summary_overlap)
            if category and skill.category == category:
                score += 2
                reasons.append(f"category {category}")
            if artifact_type and skill.outputs.artifact_type == artifact_type:
                score += 4
                reasons.append(f"produces {artifact_type}")
            if hinted and skill.id in hinted:
                score += 3
                reasons.append("suggested by intent analysis")
            if preferred_methods and any(m.lower() in (skill.name + skill.methodology.name).lower() for m in preferred_methods):
                score += 1.5
                reasons.append("preferred method")
            if score > 0:
                scored.append(Candidate(skill, score, tuple(reasons)))
        scored.sort(key=lambda c: (-c.score, c.skill.id))
        selected = scored[:limit]
        # Composition: include the natural follow-ups of the best candidate so workflows can be proposed.
        if selected:
            for follow in selected[0].skill.composes_with:
                if len(selected) >= limit + 3:
                    break
                if all(c.skill.id != follow for c in selected):
                    selected.append(Candidate(self.registry.get(follow), 0.5, ("composes with top candidate",)))
        return selected
