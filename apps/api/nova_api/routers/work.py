"""Work (tasks), projects, Skills, workflows, Today, activity, search, feedback, meta."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.artifacts.registry import get_artifact_registry
from nova.config import get_settings
from nova.domain.agents import AgentProfile
from nova.domain.enums import AutonomyMode, SkillCategory
from nova.infra.db import get_session
from nova.infra.models import Artifact, IntegrationReference, Task, Workflow
from nova.services import activity as activity_service
from nova.services import projects as project_service
from nova.services import today as today_service
from nova.services.access import AccessDenied, project_role, require_task
from nova.services.feedback import FeedbackIn, submit_feedback
from nova.skills.registry import get_skill_registry
from nova_api.auth import CurrentPrincipal

router = APIRouter(tags=["work"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]

TAB_STATUSES = {
    "active": ["queued", "running", "waiting_user", "paused"],
    "scheduled": ["scheduled"],
    "completed": ["completed"],
    "failed": ["failed", "cancelled"],
}


async def _task_view(session: AsyncSession, task: Task, *, detail: bool = False) -> dict[str, Any]:
    skills = get_skill_registry()
    steps = [
        {
            "id": s.step_key,
            "title": s.title,
            "skill_id": s.skill_id,
            "skill_name": skills.get(s.skill_id).name if s.skill_id and skills.has(s.skill_id) else None,
            "skill_version": s.skill_version,
            # the sub-agent carrying out the step (the owner of its Skill)
            "agent": skills.get(s.skill_id).agent.value if s.skill_id and skills.has(s.skill_id) else "product",
            "status": s.status,
            "detail": s.detail,
            "artifact_id": str(s.artifact_id) if s.artifact_id else None,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "finished_at": s.finished_at.isoformat() if s.finished_at else None,
            # what NOVA recorded as orchestrator: sub-objective, routing reason, Validation agent result, handoff
            "goal": (s.report or {}).get("goal", ""),
            "rationale": (s.report or {}).get("rationale", ""),
            "validation": (s.report or {}).get("validation"),
            "handoff": (s.report or {}).get("handoff"),
        }
        for s in task.steps
    ]
    evaluation = await session.scalar(
        select(IntegrationReference.data).where(
            IntegrationReference.system == "forge",
            IntegrationReference.kind == "evaluation",
            IntegrationReference.nova_type == "task",
            IntegrationReference.nova_id == str(task.id),
        )
    )
    end = task.finished_at
    duration = (end - task.started_at).total_seconds() if end and task.started_at else None
    view = {
        "id": str(task.id),
        "objective": task.objective,
        "status": task.status,
        "phase": task.phase,
        "phase_label": task.phase_label,
        "project_id": str(task.project_id) if task.project_id else None,
        "conversation_id": str(task.conversation_id) if task.conversation_id else None,
        "skills": [s["skill_name"] for s in steps if s["skill_name"]],
        "agents": list(dict.fromkeys(s["agent"] for s in steps)),
        "progress_done": task.progress_done,
        "progress_total": task.progress_total,
        "created_at": task.created_at.isoformat(),
        "scheduled_for": task.scheduled_for.isoformat() if task.scheduled_for else None,
        "duration_seconds": duration,
        "trace_id": task.trace_id,
        "evaluation": evaluation,
        "error": task.error,
        "artifact_ids": [s["artifact_id"] for s in steps if s["artifact_id"]],
        "steps": steps,
    }
    if detail:
        artifacts = (await session.scalars(select(Artifact).where(Artifact.task_id == task.id))).all()
        view.update(
            waiting_for=task.waiting_for,
            usage=task.usage,
            model=task.model,
            autonomy=task.autonomy,
            artifacts=[{"id": str(a.id), "title": a.title, "type": a.type, "version": a.current_version} for a in artifacts],
        )
    return view


@router.get("/tasks")
async def list_tasks(
    principal: CurrentPrincipal,
    session: SessionDep,
    tab: Literal["active", "scheduled", "completed", "failed"] = "active",
    project_id: str | None = None,
    limit: int = Query(50, le=200),
) -> list[dict[str, Any]]:
    query = select(Task).where(
        Task.user_id == uuid.UUID(principal.user_id), Task.status.in_(TAB_STATUSES[tab]), Task.origin != "forge_protocol"
    )
    if project_id:
        query = query.where(Task.project_id == uuid.UUID(project_id))
    rows = (await session.scalars(query.order_by(Task.created_at.desc()).limit(limit))).all()
    return [await _task_view(session, t) for t in rows]


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    return await _task_view(session, await require_task(session, task_id, principal), detail=True)


# --- Projects ----------------------------------------------------------------------------------------


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


@router.get("/projects")
async def list_projects(principal: CurrentPrincipal, session: SessionDep) -> list[dict[str, Any]]:
    return await project_service.list_projects(session, principal)


@router.post("/projects/sync")
async def sync_projects(principal: CurrentPrincipal, session: SessionDep) -> dict[str, int]:
    synced = await project_service.sync_from_orbit(session, principal)
    await session.commit()
    return {"synced": synced}


@router.post("/projects", status_code=201)
async def create_project(body: ProjectIn, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    project = await project_service.create_project(session, principal, name=body.name, description=body.description)
    await session.commit()
    return project


@router.get("/projects/{project_id}")
async def get_project(project_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    return await project_service.project_detail(session, principal, project_id)


# --- Skills & workflows ------------------------------------------------------------------------------


def _skill_view(spec: Any, *, detail: bool = False) -> dict[str, Any]:
    artifact_type = get_artifact_registry().types.get(spec.outputs.artifact_type)
    view = {
        "id": spec.id,
        "name": spec.name,
        "version": spec.version,
        "category": spec.category.value,
        "agent": spec.agent.value,
        "summary": spec.summary,
        "artifact_type": spec.outputs.artifact_type,
        "artifact_type_name": artifact_type.name if artifact_type else None,
        "steps": [{"id": s.id, "title": s.title} for s in spec.steps],
        "triggers": spec.triggers,
        "translations": {
            lang: {**t, "artifact_type_name": (artifact_type.translations.get(lang, {}).get("name") if artifact_type else None)}
            for lang, t in spec.translations.items()
        },
    }
    if detail:
        view.update(
            purpose=spec.purpose,
            inputs=[i.model_dump() for i in spec.inputs],
            methodology=spec.methodology.model_dump(),
            tools=spec.tools,
            expected_context=spec.expected_context.model_dump(),
            composes_with=spec.composes_with,
            evaluation=spec.evaluation.model_dump(),
            instructions=spec.instructions,
            content_hash=spec.content_hash,
            mode=spec.outputs.mode,
            steps=[s.model_dump() for s in spec.steps],
        )
    return view


@router.get("/skills")
async def list_skills(
    principal: CurrentPrincipal, category: SkillCategory | None = None, agent: AgentProfile | None = None
) -> list[dict[str, Any]]:
    return [
        _skill_view(s)
        for s in get_skill_registry().all(include_system=False)
        if (category is None or s.category == category) and (agent is None or s.agent == agent)
    ]


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str, principal: CurrentPrincipal) -> dict[str, Any]:
    registry = get_skill_registry()
    if not registry.has(skill_id):
        raise AccessDenied
    return _skill_view(registry.get(skill_id), detail=True)


@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    workflow = await session.get(Workflow, uuid.UUID(workflow_id))
    if workflow is None or str(workflow.created_by) != principal.user_id:
        raise AccessDenied
    return {"id": str(workflow.id), "objective": workflow.objective, "steps": workflow.steps, "source": workflow.source}


# --- Today, activity, search, feedback ---------------------------------------------------------------


@router.get("/today")
async def today(request: Request, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    return await today_service.today(session, principal, request.headers.get("accept-language"))


class DismissIn(BaseModel):
    id: str = Field(min_length=1, max_length=200)


@router.post("/today/dismiss", status_code=204)
async def dismiss_recommendation(body: DismissIn, principal: CurrentPrincipal, session: SessionDep) -> None:
    """Ignore a Home recommendation (kept per user; a recommendation with new facts gets a new id)."""
    await today_service.dismiss(session, principal, body.id)
    await session.commit()


@router.get("/activity")
async def activity(
    request: Request,
    principal: CurrentPrincipal,
    session: SessionDep,
    project_id: str | None = None,
    skill_id: str | None = None,
    artifact_id: str | None = None,
    status: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict[str, Any]]:
    if project_id and await project_role(session, uuid.UUID(project_id), uuid.UUID(principal.user_id)) is None:
        raise AccessDenied
    return await activity_service.activity(
        session,
        principal,
        project_id=project_id,
        skill_id=skill_id,
        artifact_id=artifact_id,
        status=status,
        since=since,
        until=until,
        accept_language=request.headers.get("accept-language"),
    )


@router.get("/search")
async def search(
    principal: CurrentPrincipal, session: SessionDep, q: str = Query(min_length=1, max_length=200)
) -> dict[str, Any]:
    return await activity_service.search(session, principal, q)


@router.post("/feedback", status_code=201)
async def feedback(body: FeedbackIn, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    result = await submit_feedback(session, principal, body)
    await session.commit()
    return result


@router.get("/meta")
async def meta(principal: CurrentPrincipal) -> dict[str, Any]:
    settings = get_settings()
    return {
        "version": settings.version,
        "model": settings.llm_model,
        "autonomy_modes": [m.value for m in AutonomyMode],
        "skill_categories": [c.value for c in SkillCategory if c != SkillCategory.artifact],
        "artifact_types": [
            {"type": t.type, "name": t.name, "icon": t.icon, "description": t.description}
            for t in get_artifact_registry().types.values()
        ],
        "orbit_url": settings.orbit_public_url,
        "forge_url": settings.forge_public_url,
    }
