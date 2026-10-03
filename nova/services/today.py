"""Home ("command center"): what NOVA knows, what it is doing, and what needs the user — all computed.

Every number comes from NOVA's database, ORBIT or FORGE; nothing is static or invented.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.artifacts.registry import get_artifact_registry
from nova.config import get_settings
from nova.domain.artifacts import ArtifactContent
from nova.domain.context import ContextChange, ContextError, ContextOverview
from nova.domain.permissions import Principal
from nova.infra.db import aware, utcnow
from nova.infra.models import (
    Artifact,
    ArtifactVersion,
    Conversation,
    IntegrationReference,
    Project,
    ProjectMember,
    ProjectReference,
    Task,
    User,
    UserPreferences,
)
from nova.services import providers
from nova.services.users import preferences_dict

STORY_ARTIFACTS = ("user_stories", "backlog", "prd", "epic", "story_map", "refinement")
MAX_DISMISSED = 200


def _subject(title: str) -> str:
    """ORBIT titles are « <type label> : <subject> » — keep the subject for prompts."""
    head, sep, tail = title.partition(" : ")
    return tail.strip() if sep and len(head) < 40 else title.strip()


def _fix(label: str, prompt: str, **extra: Any) -> dict[str, Any]:
    return {"kind": "fix", "label": label, "prompt": prompt, **extra}


def _review(label: str, href: str) -> dict[str, Any]:
    return {"kind": "review", "label": label, "href": href}


IGNORE = {"kind": "ignore", "label": "Ignore"}


def recommendation_for_change(change: ContextChange, project: dict[str, Any]) -> dict[str, Any] | None:
    """Deterministic mapping of ORBIT change types to suggested actions (ORBIT's own wording is displayed)."""
    subject = _subject(change.title)
    orbit_url = project.get("orbit_url") or ""
    base = {
        "id": f"orbit:{change.id}",
        "source": "orbit",
        "project_id": project["id"],
        "project_name": project["name"],
        "classification": change.classification,
        "at": change.created_at.isoformat(),
        "title": change.title,
        "subtitle": change.summary or change.type_label,
        "context": f"ORBIT · {change.type_label}",
    }
    kind = (change.data or {}).get("kind")
    if change.type == "document.new_version":
        return {
            **base,
            "suggestion": f"NOVA can check which of your artifacts are affected by the new version of “{subject}”.",
            "actions": [
                _fix("Check impact with NOVA", f'Review the impact of the new version of "{subject}" on my work.'),
                IGNORE,
            ],
        }
    if change.type in ("memory.created", "memory.validated") and kind in (None, "decision"):
        return {
            **base,
            "suggestion": "NOVA can list the artifacts this decision affects.",
            "actions": [_fix("Check affected work", f'Which of my artifacts are affected by the decision "{subject}"?'), IGNORE],
        }
    if change.type == "memory.superseded":
        return {
            **base,
            "suggestion": "NOVA can tell you what to update now that it was superseded.",
            "actions": [_fix("Find what to update", f'"{subject}" was superseded. What should I update?'), IGNORE],
        }
    if change.type == "memory.conflict_detected":
        return {
            **base,
            "risk": True,
            "suggestion": "Two pieces of project knowledge contradict each other. Resolve it in ORBIT so NOVA uses the right one.",
            "actions": [_review("Resolve in ORBIT", f"{orbit_url}/inbox"), IGNORE],
        }
    if change.type == "document.stale":
        return {
            **base,
            "suggestion": "NOVA can draft a refreshed version from the latest project context.",
            "actions": [_fix("Refresh with NOVA", f'Help me refresh "{subject}".'), IGNORE],
        }
    return None


async def _missing_acceptance_criteria(session: AsyncSession, uid: uuid.UUID) -> dict[str, Any] | None:
    members = select(ProjectMember.project_id).where(ProjectMember.user_id == uid)
    rows = (
        await session.execute(
            select(Artifact, ArtifactVersion.content, Project.name)
            .join(
                ArtifactVersion,
                (ArtifactVersion.artifact_id == Artifact.id) & (ArtifactVersion.version == Artifact.current_version),
            )
            .outerjoin(Project, Project.id == Artifact.project_id)
            .where(
                or_(Artifact.owner_id == uid, Artifact.project_id.in_(members)),
                Artifact.type.in_(STORY_ARTIFACTS),
                Artifact.status != "archived",
            )
            .order_by(Artifact.updated_at.desc())
            .limit(20)
        )
    ).all()
    types = get_artifact_registry().types
    for artifact, raw, project_name in rows:
        content = ArtifactContent.model_validate(raw)
        missing = [i for _, i in content.all_items() if i.kind == "story" and not i.attributes.get("acceptance_criteria")]
        if not missing:
            continue
        n = len(missing)
        stories = "stories" if n > 1 else "story"
        type_name = types[artifact.type].name if artifact.type in types else artifact.type
        return {
            "id": f"nova:ac:{artifact.id}:{n}",
            "source": "nova",
            "project_id": str(artifact.project_id) if artifact.project_id else None,
            "project_name": project_name,
            "classification": artifact.classification,
            "title": f"{n} {stories} need acceptance criteria",
            "subtitle": artifact.title,
            "context": f"{type_name} · Backlog quality",
            "suggestion": f"NOVA can generate acceptance criteria for {'these' if n > 1 else 'this'} {n} {stories}.",
            "actions": [
                _fix(
                    "Fix with NOVA",
                    "/acceptance-criteria Complete the missing acceptance criteria of the referenced artifact.",
                    artifact_id=str(artifact.id),
                    artifact_title=artifact.title,
                ),
                _review("Review", f"/artifacts/{artifact.id}"),
                IGNORE,
            ],
            "artifact_id": str(artifact.id),
            "at": artifact.updated_at.isoformat(),
        }
    return None


WAITING_COPY = {
    "approval": ("NOVA prepared changes and needs your approval", "Review changes"),
    "confirm_workflow": ("NOVA proposed a workflow and waits for your go", "Review the plan"),
    "questions": ("NOVA needs a clarification to continue", "Answer"),
}


def _waiting_recommendation(task: Task, project_name: str | None) -> dict[str, Any]:
    kind = (task.waiting_for or {}).get("kind", "")
    suggestion, label = WAITING_COPY.get(kind, ("NOVA is waiting for you", "Continue"))
    href = f"/c/{task.conversation_id}" if task.conversation_id else f"/work?task={task.id}"
    return {
        "id": f"nova:waiting:{task.id}",
        "source": "nova",
        "project_id": str(task.project_id) if task.project_id else None,
        "project_name": project_name,
        "title": task.objective[:140],
        "subtitle": suggestion,
        "context": "Waiting for you",
        "suggestion": suggestion + ".",
        "actions": [_review(label, href)],
        "task_id": str(task.id),
        "conversation_id": str(task.conversation_id) if task.conversation_id else None,
        "at": task.created_at.isoformat(),
        "urgent": True,
    }


def _failed_recommendation(task: Task, project_name: str | None) -> dict[str, Any]:
    return {
        "id": f"nova:failed:{task.id}",
        "source": "nova",
        "project_id": str(task.project_id) if task.project_id else None,
        "project_name": project_name,
        "title": task.objective[:140],
        "subtitle": task.error or "The task stopped before the end.",
        "context": "Didn't finish",
        "suggestion": "NOVA can resume from the last completed step.",
        "actions": [{"kind": "retry", "label": "Retry", "task_id": str(task.id)}, IGNORE],
        "task_id": str(task.id),
        "conversation_id": str(task.conversation_id) if task.conversation_id else None,
        "at": task.created_at.isoformat(),
        "risk": True,
    }


async def _overview(user_id: str, slug: str) -> ContextOverview | None:
    try:
        return await providers.context().overview(user_id, slug)
    except (ContextError, NotImplementedError, AttributeError):
        return None


async def dismiss(session: AsyncSession, principal: Principal, recommendation_id: str) -> None:
    prefs = await session.get(UserPreferences, uuid.UUID(principal.user_id))
    if prefs is None:
        prefs = UserPreferences(user_id=uuid.UUID(principal.user_id))
        session.add(prefs)
    dismissed = [d for d in (prefs.dismissed_recommendations or []) if d != recommendation_id]
    prefs.dismissed_recommendations = [*dismissed, recommendation_id][-MAX_DISMISSED:]
    await session.flush()


async def today(session: AsyncSession, principal: Principal) -> dict[str, Any]:
    uid = uuid.UUID(principal.user_id)
    user = await session.get(User, uid)
    assert user is not None
    prefs_row = await session.get(UserPreferences, uid)
    prefs = preferences_dict(prefs_row, user)
    dismissed = set(prefs_row.dismissed_recommendations or []) if prefs_row else set()
    now = utcnow()

    project_names = dict(
        (
            await session.execute(
                select(Project.id, Project.name)
                .join(ProjectMember, ProjectMember.project_id == Project.id)
                .where(ProjectMember.user_id == uid)
            )
        ).all()
    )

    def name_of(pid: uuid.UUID | None) -> str | None:
        return project_names.get(pid) if pid else None

    recommendations: list[dict[str, Any]] = []
    waiting = (
        await session.scalars(
            select(Task).where(Task.user_id == uid, Task.status == "waiting_user").order_by(Task.created_at.desc()).limit(3)
        )
    ).all()
    recommendations += [_waiting_recommendation(t, name_of(t.project_id)) for t in waiting]
    failed = (
        await session.scalars(
            select(Task)
            .where(Task.user_id == uid, Task.status == "failed", Task.created_at >= now - timedelta(days=3))
            .order_by(Task.created_at.desc())
            .limit(2)
        )
    ).all()
    recommendations += [_failed_recommendation(t, name_of(t.project_id)) for t in failed]
    if ac := await _missing_acceptance_criteria(session, uid):
        recommendations.append(ac)

    # --- ORBIT: changes, context available ---------------------------------------------------------
    identity = await providers.context().identity(principal.user_id)
    context: dict[str, Any] = {
        "system": "ORBIT",
        "linked": identity.linked,
        "account": identity.email,
        "error": None,
        "projects": [],
        "totals": {"documents": 0, "memory_items": 0, "decisions": 0, "sources": 0},
        "changes_24h": 0,
        "last_change_at": None,
    }
    orbit_risk_projects: set[str] = set()
    if identity.linked:
        linked = (
            await session.execute(
                select(Project, ProjectReference)
                .join(ProjectMember, ProjectMember.project_id == Project.id)
                .join(ProjectReference, (ProjectReference.project_id == Project.id) & (ProjectReference.system == "orbit"))
                .where(ProjectMember.user_id == uid)
                .order_by(Project.updated_at.desc())
                .limit(4)
            )
        ).all()
        since = now - timedelta(days=7)
        overviews = await asyncio.gather(*(_overview(principal.user_id, ref.external_id) for _, ref in linked))
        for (project, ref), overview in zip(linked, overviews, strict=True):
            info = {"id": str(project.id), "name": project.name, "orbit_url": ref.url}
            if overview is not None:
                context["projects"].append({"id": str(project.id), "name": project.name, "url": ref.url, **overview.model_dump()})
                for key in context["totals"]:
                    context["totals"][key] += getattr(overview, key)
            try:
                changes = await providers.context().recent_changes(principal.user_id, ref.external_id, since)
            except ContextError as exc:
                if exc.code != "not_found":  # a NOVA project may simply not exist in ORBIT
                    context["error"] = exc.message
                continue
            for change in changes:
                created = aware(change.created_at)
                if created >= now - timedelta(hours=24):
                    context["changes_24h"] += 1
                if context["last_change_at"] is None or created.isoformat() > context["last_change_at"]:
                    context["last_change_at"] = created.isoformat()
                if change.type == "memory.conflict_detected":
                    orbit_risk_projects.add(project.name)
                if (rec := recommendation_for_change(change, info)) and all(
                    r.get("title") != rec["title"] for r in recommendations
                ):
                    recommendations.append(rec)

    recommendations = [r for r in recommendations if r["id"] not in dismissed]

    # --- Work: running, results, continue ------------------------------------------------------------
    active = (
        await session.scalars(
            select(Task)
            .where(Task.user_id == uid, Task.origin == "interactive", Task.status.in_(("queued", "running", "paused")))
            .order_by(Task.created_at.desc())
        )
    ).all()
    completed_24h = await session.scalar(
        select(func.count(Task.id)).where(
            Task.user_id == uid, Task.status == "completed", Task.finished_at >= now - timedelta(hours=24)
        )
    )
    failed_projects = {name_of(t.project_id) for t in failed if t.project_id}
    at_risk = sorted({p for p in failed_projects | orbit_risk_projects if p})

    conversations = (
        await session.execute(
            select(Conversation, Project.name)
            .outerjoin(Project, Project.id == Conversation.project_id)
            .where(Conversation.user_id == uid, Conversation.archived.is_(False))
            .order_by(Conversation.updated_at.desc())
            .limit(3)
        )
    ).all()
    continue_items = [
        {"conversation_id": str(c.id), "title": c.title, "project_name": pname, "updated_at": aware(c.updated_at).isoformat()}
        for c, pname in conversations
    ]

    # --- FORGE: latest evaluation of the user's work -------------------------------------------------
    settings = get_settings()
    recent_task_ids = [
        str(t)
        for t in (
            await session.scalars(select(Task.id).where(Task.user_id == uid).order_by(Task.created_at.desc()).limit(50))
        ).all()
    ]
    last_eval = (
        await session.scalar(
            select(IntegrationReference)
            .where(
                IntegrationReference.system == "forge",
                IntegrationReference.kind == "evaluation",
                IntegrationReference.nova_type == "task",
                IntegrationReference.nova_id.in_(recent_task_ids),
            )
            .order_by(IntegrationReference.updated_at.desc())
            .limit(1)
        )
        if recent_task_ids
        else None
    )
    quality = {
        "system": "FORGE",
        "monitoring": bool(settings.forge_api_key),
        "last_evaluation": (
            {
                "score": (last_eval.data or {}).get("composite_score"),
                "passed": (last_eval.data or {}).get("passed"),
                "status": (last_eval.data or {}).get("status"),
                "url": (last_eval.data or {}).get("url"),
                "at": aware(last_eval.updated_at).isoformat(),
            }
            if last_eval
            else None
        ),
        "url": settings.forge_public_url,
    }

    # --- NOVA's own state ----------------------------------------------------------------------------
    if any(t.status == "running" for t in active):
        running_phase = next(t.phase for t in active if t.status == "running")
        state = "thinking" if running_phase in ("idle", "retrieving_context", "planning") else "working"
    elif any(r.get("urgent") and "clarification" in r.get("subtitle", "") for r in recommendations):
        state = "clarification"
    elif waiting:
        state = "waiting"
    elif any(t.status == "queued" for t in active):
        state = "working"
    elif completed_24h:
        state = "completed"
    else:
        state = "idle"

    recommendations = recommendations[:20]
    actions_required = len(recommendations)
    return {
        "user": {"display_name": user.display_name, "first_name": user.display_name.split(" ")[0], "title": user.title},
        "nova": {"name": prefs.get("nova_name", "NOVA"), "avatar": prefs.get("avatar"), "state": state},
        "onboarding_completed": prefs.get("onboarding_completed", False),
        "brief": {
            "actions_required": actions_required,
            "running": sum(1 for t in active if t.status in ("queued", "running")),
            "paused": sum(1 for t in active if t.status == "paused"),
            "waiting": len(waiting),
            "results_ready": completed_24h or 0,
            "projects_at_risk": at_risk,
        },
        "recommendations": recommendations[:20],
        "continue": continue_items,
        "context": context,
        "quality": quality,
        # Back-compat for older clients.
        "orbit": {"linked": identity.linked, "error": context["error"]},
    }
