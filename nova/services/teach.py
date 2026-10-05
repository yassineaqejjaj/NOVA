"""Teach NOVA: "watch me do it once" — NOVA observes the user's work, then saves it as a reusable Skill.

Observation covers what the user does in NOVA (requests, Skills used, edits and approvals of Artifacts) between
``start`` and ``finish``; work done elsewhere (Jira, Slack…) is described by the user in a few lines. NOVA then
generalises the steps into a learned Skill: existing Skills chained with the user's own instructions. Running it
(``/<slug>`` in the composer, a routine, or the Skills page) starts a NOVA task with those Skills.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.domain.llm import LLMMessage
from nova.domain.outputs import LearnedSkillDraft
from nova.domain.trust import TRUST_RULES
from nova.infra.db import aware, utcnow
from nova.infra.models import Artifact, ArtifactVersion, AuditEvent, LearnedSkill, Task, UserPreferences
from nova.services import providers
from nova.skills.registry import get_skill_registry
from nova.skills.router import SkillRouter

SLUG = re.compile(r"[^a-z0-9]+")


class TeachError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def slugify(name: str) -> str:
    import unicodedata

    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return SLUG.sub("-", plain).strip("-")[:60] or "my-skill"


async def observed(session: AsyncSession, user_id: uuid.UUID, since: Any) -> list[dict[str, Any]]:
    """What the user did in NOVA since ``since``, in order: requests, Skills, Artifact edits and approvals."""
    registry = get_skill_registry()
    events: list[dict[str, Any]] = []
    tasks = (
        await session.scalars(select(Task).where(Task.user_id == user_id, Task.created_at >= since).order_by(Task.created_at))
    ).all()
    for task in tasks:
        if task.origin in ("goal", "routine"):
            continue  # NOVA's own missions are not the user's workflow
        skills = [s.skill_id for s in task.steps if s.skill_id and registry.has(s.skill_id) and s.skill_id != "artifact-edit"]
        events.append(
            {
                "at": aware(task.created_at).isoformat(),
                "kind": "request",
                "text": task.objective.strip().splitlines()[0][:300] if task.objective.strip() else "",
                "skills": skills,
            }
        )
    edits = (
        await session.execute(
            select(ArtifactVersion, Artifact)
            .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
            .where(
                ArtifactVersion.author_type == "user", ArtifactVersion.author_id == user_id, ArtifactVersion.created_at >= since
            )
            .order_by(ArtifactVersion.created_at)
        )
    ).all()
    for version, artifact in edits:
        events.append(
            {
                "at": aware(version.created_at).isoformat(),
                "kind": "edit",
                "text": f"{artifact.title} — {', '.join(version.changed_sections or [])}"[:300],
                "skills": [],
            }
        )
    audits = (
        await session.scalars(
            select(AuditEvent).where(
                AuditEvent.actor_id == user_id,
                AuditEvent.created_at >= since,
                AuditEvent.action.in_(("artifact.approve", "artifact.status", "goal.done")),
            )
        )
    ).all()
    for event in audits:
        events.append(
            {
                "at": aware(event.created_at).isoformat(),
                "kind": "decision",
                "text": f"{event.action} {event.summary or ''}".strip()[:300],
                "skills": [],
            }
        )
    events.sort(key=lambda e: e["at"])
    return events


async def start(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    prefs = await session.get(UserPreferences, user_id)
    assert prefs is not None
    prefs.teaching_since = utcnow()
    return {"active": True, "since": prefs.teaching_since.isoformat()}


async def status(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    prefs = await session.get(UserPreferences, user_id)
    since = prefs.teaching_since if prefs else None
    if since is None:
        return {"active": False, "since": None, "observed": []}
    return {"active": True, "since": aware(since).isoformat(), "observed": await observed(session, user_id, since)}


async def cancel(session: AsyncSession, user_id: uuid.UUID) -> None:
    prefs = await session.get(UserPreferences, user_id)
    if prefs is not None:
        prefs.teaching_since = None


async def finish(session: AsyncSession, user_id: uuid.UUID, *, description: str, lang: str) -> dict[str, Any]:
    """Ends the observation and asks NOVA to generalise it into a draft Skill (not saved yet)."""
    prefs = await session.get(UserPreferences, user_id)
    since = prefs.teaching_since if prefs else None
    events = await observed(session, user_id, since) if since else []
    if not events and not description.strip():
        raise TeachError("nothing_observed", "NOVA did not see any step. Do your task in NOVA, or describe it.")
    registry = get_skill_registry()
    used = [s for e in events for s in e["skills"]]
    text = " ".join(e["text"] for e in events) + " " + description
    candidates = list(dict.fromkeys([*used, *(c.skill.id for c in SkillRouter(registry).candidates(text, limit=10))]))
    lines = [f"- {sid}: {registry.get(sid).name} — {registry.get(sid).summary}" for sid in candidates if registry.has(sid)]
    observed_text = (
        "\n".join(
            f"{i + 1}. [{e['kind']}] {e['text']}" + (f" (Skills: {', '.join(e['skills'])})" if e["skills"] else "")
            for i, e in enumerate(events)
        )
        or "none"
    )
    system = (
        "You are NOVA, a member of a product team. The user just showed you how they do a recurring piece of work. "
        "Turn what you OBSERVED (in NOVA) and what the user DESCRIBED (done elsewhere) into a reusable workflow: "
        "2 to 12 ordered steps, generalised (no one-off names, dates or numbers), each with a Skill from CANDIDATE "
        f"SKILLS when one does it. Write the name, description and steps in '{lang}'.\n\n" + TRUST_RULES
    )
    user = (
        f"OBSERVED IN NOVA:\n{observed_text}\n\nDESCRIBED BY THE USER:\n{description.strip() or 'none'}\n\nCANDIDATE SKILLS:\n"
        + "\n".join(lines)
    )
    result = await providers.llm().structured_output(
        [LLMMessage(role="system", content=system), LLMMessage(role="user", content=user)], LearnedSkillDraft
    )
    draft: LearnedSkillDraft = result.value
    allowed = set(candidates)
    steps = [{**s.model_dump(), "skill_id": s.skill_id if s.skill_id in allowed else None} for s in draft.steps]
    if prefs is not None:
        prefs.teaching_since = None
    return {
        "name": draft.name,
        "slug": slugify(draft.name),
        "description": draft.description,
        "steps": steps,
        "routine_suggestion": draft.routine_suggestion,
        "observed": events,
        "lang": lang,
        "since": aware(since).isoformat() if since else None,
    }


def view(skill: LearnedSkill) -> dict[str, Any]:
    return {
        "id": str(skill.id),
        "slug": skill.slug,
        "name": skill.name,
        "description": skill.description,
        "steps": skill.steps,
        "uses": skill.uses,
        "lang": skill.lang,
        "observed": (skill.source or {}).get("observed", []),
        "created_at": aware(skill.created_at).isoformat(),
    }


async def save(session: AsyncSession, user_id: uuid.UUID, data: dict[str, Any]) -> LearnedSkill:
    registry = get_skill_registry()
    slug = slugify(data.get("slug") or data["name"])
    if registry.has(slug):
        slug = f"my-{slug}"[:60]
    taken = set((await session.scalars(select(LearnedSkill.slug).where(LearnedSkill.user_id == user_id))).all())
    base, n = slug, 2
    while slug in taken:
        slug, n = f"{base}-{n}"[:60], n + 1
    steps = [
        {
            "title": str(s.get("title", ""))[:200],
            "instruction": str(s.get("instruction", ""))[:1000],
            "skill_id": s.get("skill_id") if s.get("skill_id") and registry.has(s["skill_id"]) else None,
        }
        for s in data.get("steps", [])
        if str(s.get("title", "")).strip()
    ]
    if len(steps) < 1:
        raise TeachError("invalid", "A learned Skill needs at least one step.")
    skill = LearnedSkill(
        user_id=user_id,
        slug=slug,
        name=str(data["name"])[:200],
        description=str(data.get("description", ""))[:1000],
        steps=steps,
        source={"observed": data.get("observed", []), "since": data.get("since")},
        lang=data.get("lang") or "en",
    )
    session.add(skill)
    await session.flush()
    return skill


def expand(skill: LearnedSkill, extra: str = "") -> tuple[str, list[str]]:
    """The request NOVA runs for a learned Skill: its Skills, in order, and the user's instructions."""
    skills = list(dict.fromkeys(s["skill_id"] for s in skill.steps if s.get("skill_id")))
    lead = "Suis ce workflow appris" if skill.lang == "fr" else "Follow this learned workflow"
    lines = [f"{i + 1}. {s['title']} — {s['instruction']}" for i, s in enumerate(skill.steps)]
    text = (
        f"{lead} « {skill.name} » :\n" + "\n".join(lines)
        if skill.lang == "fr"
        else f'{lead} "{skill.name}":\n' + "\n".join(lines)
    )
    if extra.strip():
        text += f"\n\n{extra.strip()}"
    return text, skills
