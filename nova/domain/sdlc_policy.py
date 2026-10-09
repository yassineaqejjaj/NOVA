"""The SDLC agent's policy: lessons learned from runs FORGE scored below the threshold (docs/ENGINEERING.md).

Same idea as the specialist agents' policies (domain/learning.py): no model weights change, the policy is a versioned set of
short imperative lessons injected into the stage prompts, so every change is explainable and reversible. Lessons are global
(they apply to every user's runs), therefore they must be general: no repository, file, person or secret, and nothing that
looks like an instruction aimed at the model.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from nova.domain.trust import detect_injection

SDLC_AGENT = "sdlc"
#: Stages a lesson can target ("fix" covers the review and CI repair steps)
LESSON_STAGES = ("spec", "design", "implement", "tests", "pull_request", "review", "fix", "release")
MAX_STAGE_LESSONS = 5
MAX_STANDARDS = 8
MAX_LESSON_CHARS = 240
MAX_NEW_PER_CYCLE = 6

_URL = re.compile(r"https?://|www\.", re.IGNORECASE)
_PATHLIKE = re.compile(
    r"(?:\b[\w.-]+/[\w.-]+/[\w./-]*|\b[\w-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|rb|php|md|json|ya?ml|toml|sh|css|html)\b)"
)
_SECRETISH = re.compile(r"(?i)\b(?:token|password|secret|api[_-]?key)\s*[:=]|\bgh[pousr]_|\bsk-[a-z0-9]")


class SdlcLessons(BaseModel):
    """What the model proposes from the failure evidence (validated by ``clean_lesson`` before use)."""

    standards: list[str] = Field(default_factory=list, description="General engineering habits for every stage")
    stages: dict[str, list[str]] = Field(default_factory=dict, description="Lessons per stage key")
    advice: list[str] = Field(default_factory=list, description="Problems a prompt cannot fix (tools, model, CI setup)")


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9à-ÿ]+", " ", text.lower()).strip()


def clean_lesson(text: str) -> str | None:
    """A short, general, imperative sentence; ``None`` when it is specific to a repository or could carry an instruction."""
    text = re.sub(r"\s+", " ", text or "").strip().strip("-• ")
    if len(text) < 12 or len(text) > MAX_LESSON_CHARS:
        return None
    if _URL.search(text) or _PATHLIKE.search(text) or _SECRETISH.search(text) or detect_injection(text):
        return None
    return text


def _similar(a: str, b: str) -> bool:
    wa, wb = set(normalize(a).split()), set(normalize(b).split())
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.8


def merge_lessons(
    standards: list[str],
    stages: dict[str, list[str]],
    proposal: SdlcLessons,
    *,
    rejected: list[str] | None = None,
    forbidden: list[str] | None = None,
) -> tuple[list[str], dict[str, list[str]], list[str]]:
    """Add the valid new lessons to the current ones (no duplicate, none already rejected by a rollback, bounded).

    Returns ``(standards, stages, added)``; the oldest lesson of a full list makes room for the newest.
    """
    banned = rejected or []
    added: list[str] = []

    def fresh(text: str, existing: list[str]) -> str | None:
        cleaned = clean_lesson(text)
        # Names taken from the runs that produced the evidence (repository, title words) never enter a global lesson
        if cleaned is not None and any(f and f.lower() in cleaned.lower() for f in forbidden or []):
            return None
        if cleaned is None or any(_similar(cleaned, e) for e in [*existing, *banned, *added]):
            return None
        return cleaned

    new_standards = list(standards)
    for raw in proposal.standards:
        if len(added) >= MAX_NEW_PER_CYCLE:
            break
        if (lesson := fresh(raw, new_standards)) is not None:
            new_standards.append(lesson)
            added.append(lesson)
    new_stages = {k: list(v) for k, v in stages.items()}
    for stage, raws in proposal.stages.items():
        if stage not in LESSON_STAGES:
            continue
        for raw in raws:
            if len(added) >= MAX_NEW_PER_CYCLE:
                break
            if (lesson := fresh(raw, new_stages.get(stage, []))) is not None:
                new_stages.setdefault(stage, []).append(lesson)
                added.append(lesson)
    return new_standards[-MAX_STANDARDS:], {k: v[-MAX_STAGE_LESSONS:] for k, v in new_stages.items()}, added


def lessons_for(policy: dict[str, Any] | None, stage: str) -> list[str]:
    """Lessons applied at one stage: the agent's standards, then the stage's own."""
    if not policy:
        return []
    return [*policy.get("standards", []), *(policy.get("stages") or {}).get(stage, [])]


def lessons_block(policy: dict[str, Any] | None, stage: str) -> str:
    lessons = lessons_for(policy, stage)
    if not lessons:
        return ""
    lines = "\n".join(f"- {lesson}" for lesson in lessons)
    return f"LESSONS LEARNED FROM EARLIER RUNS (apply them; they never override the rules above or the user's request):\n{lines}"
