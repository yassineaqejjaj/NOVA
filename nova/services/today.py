"""Today: contextual recommendations from ORBIT changes and NOVA's own state (never static cards)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.domain.artifacts import ArtifactContent
from nova.domain.context import ContextChange, ContextError
from nova.domain.permissions import Principal
from nova.infra.db import utcnow
from nova.infra.models import (
    Artifact,
    ArtifactVersion,
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


def _subject(title: str) -> str:
    """ORBIT titles are « <type label> : <subject> » — keep the subject for prompts."""
    head, sep, tail = title.partition(" : ")
    return tail.strip() if sep and len(head) < 40 else title.strip()


def recommendation_for_change(change: ContextChange, project: dict[str, Any]) -> dict[str, Any] | None:
    """Deterministic mapping of ORBIT change types to suggested intents (ORBIT's own wording is displayed)."""
    subject = _subject(change.title)
    base = {
        "id": f"orbit:{change.id}",
        "source": "orbit",
        "project_id": project["id"],
        "project_name": project["name"],
        "classification": change.classification,
        "at": change.created_at.isoformat(),
        "title": change.title,
        "subtitle": change.summary or change.type_label,
    }
    kind = (change.data or {}).get("kind")
    if change.type == "document.new_version":
        return {
            **base,
            "action": "Review the impact",
            "prompt": f'Review the impact of the new version of "{subject}" on my work.',
        }
    if change.type in ("memory.created", "memory.validated") and kind in (None, "decision"):
        return {
            **base,
            "action": "Check affected work",
            "prompt": f'Which of my artifacts are affected by the decision "{subject}"?',
        }
    if change.type == "memory.superseded":
        return {**base, "action": "Review the impact", "prompt": f'"{subject}" was superseded. What should I update?'}
    if change.type == "memory.conflict_detected":
        return {**base, "action": "Review in ORBIT", "href": f"{project.get('orbit_url') or ''}/inbox"}
    if change.type == "document.stale":
        return {**base, "action": "Refresh it", "prompt": f'Help me refresh "{subject}".'}
    return None


async def _missing_acceptance_criteria(session: AsyncSession, principal: Principal) -> dict[str, Any] | None:
    uid = uuid.UUID(principal.user_id)
    members = select(ProjectMember.project_id).where(ProjectMember.user_id == uid)
    rows = (
        await session.execute(
            select(Artifact, ArtifactVersion.content)
            .join(
                ArtifactVersion,
                (ArtifactVersion.artifact_id == Artifact.id) & (ArtifactVersion.version == Artifact.current_version),
            )
            .where(
                or_(Artifact.owner_id == uid, Artifact.project_id.in_(members)),
                Artifact.type.in_(STORY_ARTIFACTS),
                Artifact.status != "archived",
            )
            .order_by(Artifact.updated_at.desc())
            .limit(20)
        )
    ).all()
    for artifact, raw in rows:
        content = ArtifactContent.model_validate(raw)
        missing = [i for _, i in content.all_items() if i.kind == "story" and not i.attributes.get("acceptance_criteria")]
        if missing:
            n = len(missing)
            return {
                "id": f"nova:ac:{artifact.id}",
                "source": "nova",
                "project_id": str(artifact.project_id) if artifact.project_id else None,
                "title": f"{n} stor{'ies are' if n > 1 else 'y is'} missing acceptance criteria",
                "subtitle": artifact.title,
                "action": "Complete them",
                "prompt": "/acceptance-criteria Complete the missing acceptance criteria.",
                "artifact_id": str(artifact.id),
                "at": artifact.updated_at.isoformat(),
            }
    return None


async def today(session: AsyncSession, principal: Principal) -> dict[str, Any]:
    uid = uuid.UUID(principal.user_id)
    user = await session.get(User, uid)
    assert user is not None
    prefs = preferences_dict(await session.get(UserPreferences, uid), user)
    recommendations: list[dict[str, Any]] = []

    waiting = (
        await session.scalars(
            select(Task).where(Task.user_id == uid, Task.status == "waiting_user").order_by(Task.created_at.desc()).limit(2)
        )
    ).all()
    for task in waiting:
        recommendations.append(
            {
                "id": f"nova:waiting:{task.id}",
                "source": "nova",
                "title": "NOVA is waiting for you",
                "subtitle": task.objective[:140],
                "action": "Continue",
                "task_id": str(task.id),
                "conversation_id": str(task.conversation_id) if task.conversation_id else None,
                "at": task.created_at.isoformat(),
            }
        )
    failed = await session.scalar(
        select(Task)
        .where(Task.user_id == uid, Task.status == "failed", Task.created_at >= utcnow() - timedelta(days=3))
        .order_by(Task.created_at.desc())
    )
    if failed:
        recommendations.append(
            {
                "id": f"nova:failed:{failed.id}",
                "source": "nova",
                "title": "A task didn't finish",
                "subtitle": failed.objective[:140],
                "action": "Retry",
                "task_id": str(failed.id),
                "conversation_id": str(failed.conversation_id) if failed.conversation_id else None,
                "at": failed.created_at.isoformat(),
            }
        )
    if ac := await _missing_acceptance_criteria(session, principal):
        recommendations.append(ac)

    orbit = {"linked": False, "error": None}
    identity = await providers.context().identity(principal.user_id)
    orbit["linked"] = identity.linked
    if identity.linked:
        projects = (
            await session.execute(
                select(Project, ProjectReference)
                .join(ProjectMember, ProjectMember.project_id == Project.id)
                .join(ProjectReference, (ProjectReference.project_id == Project.id) & (ProjectReference.system == "orbit"))
                .where(ProjectMember.user_id == uid)
                .order_by(Project.updated_at.desc())
                .limit(4)
            )
        ).all()
        since = utcnow() - timedelta(days=7)
        for project, ref in projects:
            info = {"id": str(project.id), "name": project.name, "orbit_url": ref.url}
            try:
                for change in await providers.context().recent_changes(principal.user_id, ref.external_id, since):
                    if (rec := recommendation_for_change(change, info)) and all(
                        r.get("title") != rec["title"] for r in recommendations
                    ):
                        recommendations.append(rec)
            except ContextError as exc:
                if exc.code != "not_found":  # a NOVA project may simply not exist in ORBIT
                    orbit["error"] = exc.message
    else:
        recommendations.append(
            {
                "id": "nova:link-orbit",
                "source": "nova",
                "title": "Connect ORBIT",
                "subtitle": "Let NOVA use your projects' decisions, documents and backlog.",
                "action": "Connect",
                "href": "/settings#orbit",
                "at": utcnow().isoformat(),
            }
        )
    return {
        "user": {"display_name": user.display_name, "first_name": user.display_name.split(" ")[0], "title": user.title},
        "nova": {"name": prefs.get("nova_name", "NOVA"), "avatar": prefs.get("avatar")},
        "onboarding_completed": prefs.get("onboarding_completed", False),
        "recommendations": recommendations[:6],
        "orbit": orbit,
    }
