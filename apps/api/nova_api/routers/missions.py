"""NOVA as a team member: Goals, Missions, Routines, Inbox, presence."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.domain.enums import AutonomyMode
from nova.i18n import resolve_lang
from nova.infra.db import aware, get_session, utcnow
from nova.infra.models import Artifact, Goal, Project, Routine, Task, UserPreferences
from nova.services import artifacts as artifact_service
from nova.services import goals as goal_service
from nova.services import routines as routine_service
from nova.services import today as today_service
from nova.services.dispatch import dispatch
from nova_api.auth import CurrentPrincipal
from nova_api.errors import ApiError

router = APIRouter(tags=["missions"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
Autonomy = Literal["observe", "suggest", "execute_with_approval", "execute_automatically"]


async def _lang(session: AsyncSession, principal: Any, request: Request) -> str:
    prefs = await session.get(UserPreferences, uuid.UUID(principal.user_id))
    return resolve_lang(prefs.language if prefs else None, request.headers.get("accept-language"))


async def _dispatch_all(ids: list[str]) -> None:
    for task_id in ids:
        await dispatch(task_id, "start")


# --- Goals ------------------------------------------------------------------------------------------------


class GoalIn(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    outcome: str = Field(default="", max_length=2000)
    due_date: datetime | None = None
    project_id: str | None = None
    autonomy: Autonomy = "execute_with_approval"
    lang: Literal["en", "fr"] | None = None


class GoalActionIn(BaseModel):
    action: Literal["approve", "pause", "resume", "archive", "start", "done", "skip", "retry"]
    milestone_id: str | None = None
    note: str = Field(default="", max_length=500)


async def _owned_goal(session: AsyncSession, principal: Any, goal_id: str) -> Goal:
    try:
        goal = await session.get(Goal, uuid.UUID(goal_id))
    except ValueError:
        goal = None
    if goal is None or str(goal.user_id) != principal.user_id:
        raise ApiError(404, "not_found", "This goal does not exist.")
    return goal


async def _project_names(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return dict((await session.execute(select(Project.id, Project.name).where(Project.id.in_(ids)))).all())


@router.get("/goals")
async def list_goals(principal: CurrentPrincipal, session: SessionDep, include_archived: bool = False) -> list[dict[str, Any]]:
    query = select(Goal).where(Goal.user_id == uuid.UUID(principal.user_id)).order_by(Goal.updated_at.desc())
    if not include_archived:
        query = query.where(Goal.status != "archived")
    goals = (await session.scalars(query.limit(100))).all()
    names = await _project_names(session, {g.project_id for g in goals if g.project_id})
    return [goal_service.goal_view(g, project_name=names.get(g.project_id) if g.project_id else None) for g in goals]


@router.post("/goals", status_code=201)
async def create_goal(body: GoalIn, request: Request, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    lang = body.lang or await _lang(session, principal, request)
    try:
        goal, ids = await goal_service.create_goal(
            session,
            principal,
            title=body.title,
            outcome=body.outcome,
            due_date=body.due_date,
            project_id=body.project_id,
            autonomy=AutonomyMode(body.autonomy),
            lang=lang,
        )
    except goal_service.GoalError as exc:
        raise ApiError(422, exc.code, str(exc)) from exc
    await session.commit()
    await _dispatch_all(ids)
    await session.refresh(goal)
    names = await _project_names(session, {goal.project_id} if goal.project_id else set())
    return goal_service.goal_view(goal, project_name=names.get(goal.project_id) if goal.project_id else None)


@router.get("/goals/{goal_id}")
async def get_goal(goal_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    goal = await _owned_goal(session, principal, goal_id)
    await goal_service.advance(session, goal)  # sync with the milestones' tasks
    await session.commit()
    names = await _project_names(session, {goal.project_id} if goal.project_id else set())
    view = goal_service.goal_view(goal, project_name=names.get(goal.project_id) if goal.project_id else None)
    task_ids = [uuid.UUID(m["task_id"]) for m in view["milestones"] if m.get("task_id")]
    if task_ids:
        tasks = {str(t.id): t for t in (await session.scalars(select(Task).where(Task.id.in_(task_ids)))).all()}
        for m in view["milestones"]:
            task = tasks.get(m.get("task_id") or "")
            if task is not None:
                m["activity"] = task.phase_label if task.status in ("running", "queued") else None
                m["task_status"] = task.status
    return view


@router.post("/goals/{goal_id}/actions")
async def goal_action(goal_id: str, body: GoalActionIn, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    goal = await _owned_goal(session, principal, goal_id)
    try:
        ids = await goal_service.act(session, goal, body.action, body.milestone_id, body.note)
    except goal_service.GoalError as exc:
        raise ApiError(409 if exc.code == "invalid_state" else 422, exc.code, str(exc)) from exc
    await session.commit()
    await _dispatch_all(ids)
    await session.refresh(goal)
    return goal_service.goal_view(goal)


# --- Routines ---------------------------------------------------------------------------------------------


class ScheduleIn(BaseModel):
    kind: Literal["manual", "daily", "weekdays", "weekly", "monthly"] = "weekly"
    time: str = Field(default="08:30", pattern=r"^\d{1,2}:\d{2}$")
    days: list[int] = Field(default_factory=list, max_length=7)
    day: int | None = Field(default=None, ge=1, le=28)
    tz: str = "Europe/Paris"


class RoutineIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    instructions: str = Field(min_length=1, max_length=4000)
    skill_ids: list[str] = Field(default_factory=list, max_length=6)
    schedule: ScheduleIn = Field(default_factory=ScheduleIn)
    autonomy: Autonomy = "execute_automatically"
    project_id: str | None = None
    template: str | None = Field(default=None, max_length=60)
    enabled: bool = True


class RoutinePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    instructions: str | None = Field(default=None, min_length=1, max_length=4000)
    skill_ids: list[str] | None = None
    schedule: ScheduleIn | None = None
    autonomy: Autonomy | None = None
    project_id: str | None = None
    enabled: bool | None = None


async def _owned_routine(session: AsyncSession, principal: Any, routine_id: str) -> Routine:
    try:
        routine = await session.get(Routine, uuid.UUID(routine_id))
    except ValueError:
        routine = None
    if routine is None or str(routine.user_id) != principal.user_id:
        raise ApiError(404, "not_found", "This routine does not exist.")
    return routine


@router.get("/routines/templates")
async def routine_templates(request: Request, principal: CurrentPrincipal, session: SessionDep) -> list[dict[str, Any]]:
    return routine_service.templates(await _lang(session, principal, request))


@router.get("/routines")
async def list_routines(principal: CurrentPrincipal, session: SessionDep) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(select(Routine).where(Routine.user_id == uuid.UUID(principal.user_id)).order_by(Routine.created_at))
    ).all()
    return [routine_service.routine_view(r) for r in rows]


@router.post("/routines", status_code=201)
async def create_routine(body: RoutineIn, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    schedule = body.schedule.model_dump(exclude_none=True)
    try:
        routine_service.validate(body.name, body.instructions, body.skill_ids, schedule)
    except routine_service.RoutineError as exc:
        raise ApiError(422, exc.code, str(exc)) from exc
    routine = Routine(
        user_id=uuid.UUID(principal.user_id),
        project_id=uuid.UUID(body.project_id) if body.project_id else None,
        name=body.name.strip(),
        instructions=body.instructions.strip(),
        skill_ids=body.skill_ids,
        schedule=schedule,
        autonomy=body.autonomy,
        template=body.template,
        enabled=body.enabled,
        next_run_at=routine_service.next_run(schedule, utcnow()) if body.enabled else None,
    )
    session.add(routine)
    await session.commit()
    return routine_service.routine_view(routine)


@router.patch("/routines/{routine_id}")
async def update_routine(routine_id: str, body: RoutinePatch, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    routine = await _owned_routine(session, principal, routine_id)
    data = body.model_dump(exclude_unset=True)
    if "schedule" in data and data["schedule"] is not None:
        data["schedule"] = body.schedule.model_dump(exclude_none=True)  # type: ignore[union-attr]
    merged = {
        "name": routine.name,
        "instructions": routine.instructions,
        "skill_ids": routine.skill_ids,
        "schedule": routine.schedule,
        **data,
    }
    try:
        routine_service.validate(merged["name"], merged["instructions"], merged["skill_ids"], merged["schedule"])
    except routine_service.RoutineError as exc:
        raise ApiError(422, exc.code, str(exc)) from exc
    for key, value in data.items():
        if key == "project_id":
            value = uuid.UUID(value) if value else None
        setattr(routine, key, value)
    routine.next_run_at = routine_service.next_run(routine.schedule, utcnow()) if routine.enabled else None
    await session.commit()
    return routine_service.routine_view(routine)


@router.delete("/routines/{routine_id}", status_code=204)
async def delete_routine(routine_id: str, principal: CurrentPrincipal, session: SessionDep) -> None:
    routine = await _owned_routine(session, principal, routine_id)
    await session.delete(routine)
    await session.commit()


@router.post("/routines/{routine_id}/run", status_code=202)
async def run_routine(routine_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    routine = await _owned_routine(session, principal, routine_id)
    task_id = await routine_service.run(session, routine, manual=True)
    await session.commit()
    await dispatch(task_id, "start")
    return {**routine_service.routine_view(routine), "task_id": task_id}


# --- Inbox, Today visits, presence ------------------------------------------------------------------------


@router.get("/inbox")
async def inbox(request: Request, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    data = await today_service.today(session, principal, request.headers.get("accept-language"))
    await session.commit()
    return data["inbox"]


class ValidateIn(BaseModel):
    inbox_id: str = Field(max_length=300)


@router.post("/inbox/validate/{artifact_id}")
async def validate_deliverable(
    artifact_id: str, body: ValidateIn, principal: CurrentPrincipal, session: SessionDep
) -> dict[str, Any]:
    """The user validates a deliverable NOVA produced: it becomes final and leaves the Inbox."""
    artifact = await session.get(Artifact, uuid.UUID(artifact_id))
    if artifact is None:
        raise ApiError(404, "not_found", "This Artifact does not exist.")
    await artifact_service.save_user_edit(
        session, principal, artifact_id, base_version=artifact.current_version, sections=None, title=None, status="final"
    )
    await today_service.dismiss(session, principal, body.inbox_id)
    await session.commit()
    return {"artifact_id": artifact_id, "status": "final"}


@router.post("/today/seen", status_code=204)
async def today_seen(principal: CurrentPrincipal, session: SessionDep) -> None:
    """The user saw Today: the next visit's "since your last visit" starts now."""
    prefs = await session.get(UserPreferences, uuid.UUID(principal.user_id))
    if prefs is not None:
        prefs.today_seen_at = utcnow()
        await session.commit()


@router.get("/presence")
async def presence(principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    """What NOVA is doing right now, for the orb: working on a mission, waiting for the user, or idle."""
    uid = uuid.UUID(principal.user_id)
    running = (
        await session.scalars(
            select(Task)
            .where(Task.user_id == uid, Task.status.in_(("running", "queued")))
            .order_by(Task.started_at.desc().nulls_last(), Task.created_at.desc())
            .limit(10)
        )
    ).all()
    waiting = (await session.scalars(select(Task.id).where(Task.user_id == uid, Task.status == "waiting_user"))).all()
    goals = (await session.scalars(select(Goal).where(Goal.user_id == uid, Goal.status == "active"))).all()
    goal_titles = {str(g.id): g.title for g in goals}
    current = running[0] if running else None
    mission = None
    if current is not None:
        goal_title = goal_titles.get((current.input or {}).get("goal_id", ""))
        mission = {
            "kind": current.origin,
            "title": goal_title or today_service.work_title(current),
            "activity": current.phase_label,
            "phase": current.phase,
            "started_at": aware(current.started_at or current.created_at).isoformat(),
            "href": f"/c/{current.conversation_id}" if current.conversation_id else f"/work?task={current.id}",
        }
    proposed = (await session.scalars(select(Goal).where(Goal.user_id == uid, Goal.status == "proposed"))).all()
    waiting_goals = sum(1 for g in [*goals, *proposed] if goal_service.mission_state(g) == "waiting")
    state = "working" if current else "waiting" if waiting or waiting_goals else "idle"
    return {"state": state, "running": len(running), "waiting": len(waiting) + waiting_goals, "mission": mission}


@router.get("/missions")
async def missions(principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    """Mission Control: every active goal, running work and the next routine runs."""
    uid = uuid.UUID(principal.user_id)
    goals = (
        await session.scalars(
            select(Goal)
            .where(Goal.user_id == uid, Goal.status.in_(("proposed", "active", "paused", "completed")))
            .order_by(Goal.updated_at.desc())
            .limit(50)
        )
    ).all()
    for goal in goals:
        if goal.status == "active":
            await goal_service.advance(session, goal)
    await session.commit()
    names = await _project_names(session, {g.project_id for g in goals if g.project_id})
    tasks = (
        await session.scalars(
            select(Task)
            .where(Task.user_id == uid, Task.status.in_(("queued", "running", "waiting_user", "paused")))
            .order_by(Task.created_at.desc())
            .limit(30)
        )
    ).all()
    routines = (
        await session.scalars(
            select(Routine).where(Routine.user_id == uid, Routine.enabled.is_(True)).order_by(Routine.next_run_at)
        )
    ).all()
    return {
        "goals": [goal_service.goal_view(g, project_name=names.get(g.project_id) if g.project_id else None) for g in goals],
        "tasks": [
            {
                "id": str(t.id),
                "title": today_service.work_title(t),
                "origin": t.origin,
                "status": t.status,
                "activity": t.phase_label,
                "goal_id": (t.input or {}).get("goal_id"),
                "routine_id": (t.input or {}).get("routine_id"),
                "conversation_id": str(t.conversation_id) if t.conversation_id else None,
                "progress_done": t.progress_done,
                "progress_total": t.progress_total,
                "started_at": aware(t.started_at or t.created_at).isoformat(),
            }
            for t in tasks
        ],
        "routines": [routine_service.routine_view(r) for r in routines],
    }


@router.get("/team")
async def team(principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    """Your product team: NOVA and the specialists it delegates to — what each is doing and has delivered (30 days)."""
    from datetime import timedelta

    from nova.domain.agents import AGENTS, AgentProfile
    from nova.infra.models import TaskStep
    from nova.skills.registry import get_skill_registry

    uid = uuid.UUID(principal.user_id)
    registry = get_skill_registry()
    rows = (
        await session.execute(
            select(TaskStep, Task)
            .join(Task, Task.id == TaskStep.task_id)
            .where(Task.user_id == uid, Task.created_at >= utcnow() - timedelta(days=30))
            .order_by(Task.created_at.desc())
            .limit(400)
        )
    ).all()
    stats: dict[str, dict[str, Any]] = {
        p.value: {
            "id": p.value,
            "skills": sum(1 for s in registry.all(include_system=False) if s.agent == p),
            "delivered": 0,
            "working": [],
            "last": None,
        }
        for p in AgentProfile
    }
    validated = revised = 0
    for step, task in rows:
        agent = registry.get(step.skill_id).agent.value if step.skill_id and registry.has(step.skill_id) else None
        if agent is None:
            continue
        entry = stats[agent]
        validation = (step.report or {}).get("validation") or {}
        if step.status == "completed":
            entry["delivered"] += 1
            validated += 1
            revised += 1 if validation.get("status") == "revised" else 0
            if entry["last"] is None and step.artifact_id:
                entry["last"] = {
                    "title": step.title,
                    "artifact_id": str(step.artifact_id),
                    "at": (step.finished_at or task.created_at).isoformat(),
                }
        elif step.status == "running" and task.status in ("running", "queued", "waiting_user"):
            entry["working"].append(
                {
                    "title": step.title,
                    "task_id": str(task.id),
                    "conversation_id": str(task.conversation_id) if task.conversation_id else None,
                    "goal_id": (task.input or {}).get("goal_id"),
                }
            )
    return {
        "agents": list(stats.values()),
        "support": {
            "validation": {"checked": validated, "revised": revised},
            "research": {"runs": len({str(t.id) for _, t in rows})},
        },
        "names": {p.value: AGENTS[p].name for p in AgentProfile},
    }


# --- Teach NOVA -------------------------------------------------------------------------------------------


class TeachFinishIn(BaseModel):
    description: str = Field(default="", max_length=4000)  # steps done outside NOVA (Jira, Slack…)
    lang: Literal["en", "fr"] | None = None


class LearnedStepIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    instruction: str = Field(default="", max_length=1000)
    skill_id: str | None = None


class LearnedSkillIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str | None = Field(default=None, max_length=80)
    description: str = Field(default="", max_length=1000)
    steps: list[LearnedStepIn] = Field(min_length=1, max_length=12)
    observed: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    since: str | None = None
    lang: Literal["en", "fr"] | None = None


@router.post("/teach/start")
async def teach_start(principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    from nova.services import teach

    result = await teach.start(session, uuid.UUID(principal.user_id))
    await session.commit()
    return result


@router.get("/teach")
async def teach_status(principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    from nova.services import teach

    return await teach.status(session, uuid.UUID(principal.user_id))


@router.post("/teach/cancel", status_code=204)
async def teach_cancel(principal: CurrentPrincipal, session: SessionDep) -> None:
    from nova.services import teach

    await teach.cancel(session, uuid.UUID(principal.user_id))
    await session.commit()


@router.post("/teach/finish")
async def teach_finish(body: TeachFinishIn, request: Request, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    from nova.services import teach

    lang = body.lang or await _lang(session, principal, request)
    try:
        draft = await teach.finish(session, uuid.UUID(principal.user_id), description=body.description, lang=lang)
    except teach.TeachError as exc:
        raise ApiError(422, exc.code, str(exc)) from exc
    await session.commit()
    return draft


@router.get("/learned-skills")
async def learned_skills(principal: CurrentPrincipal, session: SessionDep) -> list[dict[str, Any]]:
    from nova.infra.models import LearnedSkill
    from nova.services import teach

    rows = (
        await session.scalars(
            select(LearnedSkill)
            .where(LearnedSkill.user_id == uuid.UUID(principal.user_id))
            .order_by(LearnedSkill.created_at.desc())
        )
    ).all()
    return [teach.view(s) for s in rows]


@router.post("/learned-skills", status_code=201)
async def save_learned_skill(
    body: LearnedSkillIn, request: Request, principal: CurrentPrincipal, session: SessionDep
) -> dict[str, Any]:
    from nova.services import teach

    data = body.model_dump()
    data["lang"] = body.lang or await _lang(session, principal, request)
    try:
        skill = await teach.save(session, uuid.UUID(principal.user_id), data)
    except teach.TeachError as exc:
        raise ApiError(422, exc.code, str(exc)) from exc
    await session.commit()
    return teach.view(skill)


async def _owned_learned(session: AsyncSession, principal: Any, skill_id: str) -> Any:
    from nova.infra.models import LearnedSkill

    try:
        skill = await session.get(LearnedSkill, uuid.UUID(skill_id))
    except ValueError:
        skill = None
    if skill is None or str(skill.user_id) != principal.user_id:
        raise ApiError(404, "not_found", "This Skill does not exist.")
    return skill


@router.delete("/learned-skills/{skill_id}", status_code=204)
async def delete_learned_skill(skill_id: str, principal: CurrentPrincipal, session: SessionDep) -> None:
    await session.delete(await _owned_learned(session, principal, skill_id))
    await session.commit()


class RunLearnedIn(BaseModel):
    project_id: str | None = None
    details: str = Field(default="", max_length=2000)


@router.post("/learned-skills/{skill_id}/run", status_code=202)
async def run_learned_skill(
    skill_id: str, body: RunLearnedIn, principal: CurrentPrincipal, session: SessionDep
) -> dict[str, Any]:
    from nova.services.conversations import ComposerInput, create_conversation, submit
    from nova.skills.registry import get_skill_registry

    skill = await _owned_learned(session, principal, skill_id)
    conversation = await create_conversation(session, principal, project_id=body.project_id, title=f"✦ {skill.name}")
    _, _, task = await submit(
        session,
        principal,
        conversation,
        ComposerInput(text=f"/{skill.slug} {body.details}".strip(), project_id=body.project_id),
        {s.id for s in get_skill_registry().all()},
    )
    await session.commit()
    await dispatch(str(task.id), "start")
    return {"conversation_id": str(conversation.id), "task_id": str(task.id)}


#: Hours a product person typically spends on a deliverable of each Skill category — an order of magnitude to
#: estimate the time NOVA saves (shown as an estimate, with this method).
HOURS_BY_CATEGORY = {
    "strategy": 4.0, "discovery": 3.0, "prioritization": 2.0, "definition": 3.0,
    "delivery": 2.0, "analysis": 2.0, "communication": 1.0, "artifact": 1.0,
}  # fmt: skip


@router.get("/impact")
async def impact(principal: CurrentPrincipal, session: SessionDep, days: int = 30) -> dict[str, Any]:
    """What NOVA did for the user over ``days``: work executed, deliverables, decisions, routines, time saved (estimate)."""
    from datetime import timedelta

    from sqlalchemy import func

    from nova.infra.models import ArtifactVersion, AuditEvent, TaskStep
    from nova.skills.registry import get_skill_registry

    uid = uuid.UUID(principal.user_id)
    since = utcnow() - timedelta(days=max(1, min(days, 365)))
    tasks = (
        await session.scalars(select(Task).where(Task.user_id == uid, Task.status == "completed", Task.finished_at >= since))
    ).all()
    registry = get_skill_registry()
    steps = (
        await session.scalars(
            select(TaskStep)
            .join(Task, Task.id == TaskStep.task_id)
            .where(Task.user_id == uid, TaskStep.status == "completed", Task.finished_at >= since)
        )
    ).all()
    hours = sum(
        HOURS_BY_CATEGORY.get(registry.get(s.skill_id).category.value, 1.0)
        for s in steps
        if s.skill_id and registry.has(s.skill_id) and s.skill_id != "artifact-edit"
    )
    artifacts = await session.scalar(
        select(func.count(func.distinct(ArtifactVersion.artifact_id)))
        .join(Task, Task.id == ArtifactVersion.task_id)
        .where(Task.user_id == uid, ArtifactVersion.author_type == "nova", ArtifactVersion.created_at >= since)
    )
    decisions = await session.scalar(
        select(func.count(AuditEvent.id)).where(
            AuditEvent.actor_id == uid,
            AuditEvent.created_at >= since,
            AuditEvent.action.in_(("goal.done", "goal.approve", "goal.start", "artifact.status")),
        )
    )
    validated = sum(1 for s in steps if ((s.report or {}).get("validation") or {}).get("status") in ("passed", "revised"))
    return {
        "days": days,
        "tasks": len(tasks),
        "by_origin": {o: sum(1 for t in tasks if t.origin == o) for o in ("interactive", "goal", "routine")},
        "artifacts": artifacts or 0,
        "deliverables_validated": validated,
        "decisions": decisions or 0,
        "hours_saved_estimate": round(hours, 1),
        "method": "hours per Skill category (strategy 4 h, discovery 3 h, definition 3 h, prioritization 2 h, delivery 2 h, analysis 2 h, communication 1 h)",
    }
