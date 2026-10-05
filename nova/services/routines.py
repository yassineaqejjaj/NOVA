"""Routines: work NOVA does on a schedule without being asked ("Every Monday 08:30, prepare my Product Brief").

A run is an ordinary NOVA task (origin ``routine``) in the routine's own conversation; its result lands in the Inbox.
The beat's minute tick starts due routines; ``run_now`` starts one on demand.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.domain.enums import AutonomyMode
from nova.infra.db import aware, utcnow
from nova.infra.models import Conversation, Routine, User
from nova.services.audit import audit
from nova.services.conversations import ComposerInput, create_conversation, submit
from nova.services.users import principal_for
from nova.skills.registry import get_skill_registry

DEFAULT_TZ = "Europe/Paris"

# id: (skills, schedule, {lang: (name, instructions)})
TEMPLATES: dict[str, dict[str, Any]] = {
    "daily-pulse": {
        "skills": [],
        "schedule": {"kind": "weekdays", "time": "08:30"},
        "en": (
            "Daily Product Pulse",
            "Review what changed in the project since yesterday (ORBIT decisions, new document versions, conflicts, stale knowledge), blocked or failed work and open risks. Report only what deserves an action today, most important first, with a recommendation for each.",
        ),
        "fr": (
            "Product Pulse quotidien",
            "Passe en revue ce qui a changé dans le projet depuis hier (décisions ORBIT, nouvelles versions de documents, conflits, connaissances obsolètes), le travail bloqué ou en échec et les risques ouverts. Ne signale que ce qui mérite une action aujourd’hui, du plus important au moins important, avec une recommandation pour chacun.",
        ),
    },
    "weekly-brief": {
        "skills": ["product-update"],
        "schedule": {"kind": "weekly", "days": [0], "time": "08:30"},
        "en": (
            "Weekly Product Brief",
            "Prepare my Weekly Product Brief: what shipped last week, what is in progress, decisions taken, risks and the priorities of the week.",
        ),
        "fr": (
            "Product Brief hebdomadaire",
            "Prépare mon Product Brief de la semaine : ce qui a été livré la semaine dernière, ce qui est en cours, les décisions prises, les risques et les priorités de la semaine.",
        ),
    },
    "sprint-readiness": {
        "skills": ["sprint-preparation"],
        "schedule": {"kind": "weekly", "days": [0], "time": "09:00"},
        "en": (
            "Sprint Readiness",
            "Before the sprint planning: analyse the top of the backlog, detect incomplete stories and propose the missing acceptance criteria.",
        ),
        "fr": (
            "Préparation du sprint",
            "Avant le sprint planning : analyse le haut du backlog, détecte les stories incomplètes et propose les critères d’acceptation manquants.",
        ),
    },
    "backlog-quality": {
        "skills": ["backlog-refinement"],
        "schedule": {"kind": "weekly", "days": [4], "time": "16:00"},
        "en": (
            "Backlog Quality",
            "Review the backlog quality: unclear stories, missing acceptance criteria, stories to split and questions for the team.",
        ),
        "fr": (
            "Qualité du backlog",
            "Revois la qualité du backlog : stories floues, critères d’acceptation manquants, stories à découper et questions pour l’équipe.",
        ),
    },
    "product-weekly": {
        "skills": ["stakeholder-brief"],
        "schedule": {"kind": "weekly", "days": [4], "time": "17:00"},
        "en": (
            "Product Weekly",
            "Prepare the Product Weekly for stakeholders: progress, decisions needed, risks and next steps.",
        ),
        "fr": (
            "Product Weekly",
            "Prépare le Product Weekly pour les parties prenantes : avancement, décisions attendues, risques et prochaines étapes.",
        ),
    },
    "interview-synthesis": {
        "skills": ["feedback-synthesis"],
        "schedule": {"kind": "manual"},
        "en": (
            "Interview synthesis",
            "Synthesise the latest user interview: extract the insights, the quotes that matter and update the hypotheses.",
        ),
        "fr": (
            "Synthèse d’interview",
            "Synthétise la dernière interview utilisateur : extrais les enseignements, les verbatims importants et mets à jour les hypothèses.",
        ),
    },
}


class RoutineError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def templates(lang: str) -> list[dict[str, Any]]:
    lang = "fr" if lang == "fr" else "en"
    return [
        {"id": key, "name": t[lang][0], "instructions": t[lang][1], "skill_ids": t["skills"], "schedule": t["schedule"]}
        for key, t in TEMPLATES.items()
    ]


def _time(schedule: dict[str, Any]) -> tuple[int, int]:
    hour, _, minute = str(schedule.get("time") or "08:30").partition(":")
    return max(0, min(23, int(hour or 8))), max(0, min(59, int(minute or 0)))


def next_run(schedule: dict[str, Any], after: datetime) -> datetime | None:
    """Next occurrence strictly after ``after`` (UTC), in the schedule's time zone. ``manual`` never runs alone."""
    kind = schedule.get("kind", "manual")
    if kind == "manual":
        return None
    tz = ZoneInfo(schedule.get("tz") or DEFAULT_TZ)
    local = after.astimezone(tz)
    hour, minute = _time(schedule)
    days = (
        {int(d) for d in schedule.get("days") or []}
        if kind == "weekly"
        else set(range(5))
        if kind == "weekdays"
        else set(range(7))
    )
    if kind == "weekly" and not days:
        days = {0}
    for offset in range(0, 62):
        candidate = (local + timedelta(days=offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= local:
            continue
        if kind == "monthly":
            if candidate.day == min(int(schedule.get("day") or 1), 28):
                return candidate.astimezone(UTC)
        elif candidate.weekday() in days:
            return candidate.astimezone(UTC)
    return None


def routine_view(routine: Routine) -> dict[str, Any]:
    return {
        "id": str(routine.id),
        "name": routine.name,
        "instructions": routine.instructions,
        "skill_ids": routine.skill_ids,
        "template": routine.template,
        "schedule": routine.schedule,
        "autonomy": routine.autonomy,
        "enabled": routine.enabled,
        "project_id": str(routine.project_id) if routine.project_id else None,
        "conversation_id": str(routine.conversation_id) if routine.conversation_id else None,
        "next_run_at": aware(routine.next_run_at).isoformat() if routine.next_run_at else None,
        "last_run_at": aware(routine.last_run_at).isoformat() if routine.last_run_at else None,
        "last_task_id": str(routine.last_task_id) if routine.last_task_id else None,
        "runs": routine.runs,
    }


def validate(name: str, instructions: str, skill_ids: list[str], schedule: dict[str, Any]) -> None:
    if not name.strip() or not instructions.strip():
        raise RoutineError("invalid", "A routine needs a name and instructions.")
    registry = get_skill_registry()
    unknown = [s for s in skill_ids if not registry.has(s)]
    if unknown:
        raise RoutineError("invalid", f"Unknown Skills: {', '.join(unknown)}")
    if schedule.get("kind") not in ("manual", "daily", "weekdays", "weekly", "monthly"):
        raise RoutineError("invalid", "Unknown schedule.")
    try:
        ZoneInfo(schedule.get("tz") or DEFAULT_TZ)
        _time(schedule)
    except (ValueError, KeyError) as exc:
        raise RoutineError("invalid", "Invalid time or time zone.") from exc


async def run(session: AsyncSession, routine: Routine, *, manual: bool = False) -> str:
    """Starts one run as a NOVA task. Returns the task id to dispatch."""
    user = await session.get(User, routine.user_id)
    assert user is not None
    principal = principal_for(user)
    conversation = await session.get(Conversation, routine.conversation_id) if routine.conversation_id else None
    if conversation is None:
        conversation = await create_conversation(
            session, principal, project_id=str(routine.project_id) if routine.project_id else None, title=f"↻ {routine.name}"
        )
        routine.conversation_id = conversation.id
    mode = AutonomyMode(routine.autonomy)
    skills = [s for s in routine.skill_ids if get_skill_registry().has(s)]
    text = (" ".join(f"/{s}" for s in skills) + " " if skills else "") + routine.instructions
    _, _, task = await submit(
        session,
        principal,
        conversation,
        ComposerInput(
            text=text,
            project_id=str(routine.project_id) if routine.project_id else None,
            skill_refs=skills,
            autonomy=AutonomyMode.suggest if mode == AutonomyMode.observe else mode,
        ),
        {s.id for s in get_skill_registry().all()},
    )
    task.origin = "routine"
    task.input = {**task.input, "routine_id": str(routine.id)}
    now = utcnow()
    routine.last_run_at, routine.last_task_id, routine.runs = now, task.id, routine.runs + 1
    if not manual or routine.next_run_at is None or aware(routine.next_run_at) <= now:
        routine.next_run_at = next_run(routine.schedule, now) if routine.enabled else None
    await audit(
        session,
        actor_id=routine.user_id,
        action="routine.run",
        target_type="routine",
        target_id=str(routine.id),
        summary=routine.name,
    )
    return str(task.id)


async def run_due(session: AsyncSession, now: datetime | None = None) -> list[str]:
    now = now or utcnow()
    due = (
        await session.scalars(
            select(Routine)
            .where(Routine.enabled.is_(True), Routine.next_run_at.is_not(None), Routine.next_run_at <= now)
            .limit(50)
        )
    ).all()
    return [await run(session, routine) for routine in due]


def parse_uuid(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None
