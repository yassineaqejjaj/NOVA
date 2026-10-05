"""Activity feed and global search (both permission-filtered)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.artifacts.registry import get_artifact_registry
from nova.domain.context import ContextError
from nova.domain.permissions import Principal
from nova.i18n import MESSAGES, Lang, resolve_lang, tr
from nova.infra.models import (
    Artifact,
    ArtifactVersion,
    AuditEvent,
    ContextRetrievalReference,
    Conversation,
    IntegrationReference,
    Project,
    ProjectMember,
    ProjectReference,
    Task,
    TaskStep,
    UserPreferences,
)
from nova.services import providers
from nova.skills.registry import get_skill_registry


async def activity(
    session: AsyncSession,
    principal: Principal,
    *,
    project_id: str | None = None,
    skill_id: str | None = None,
    artifact_id: str | None = None,
    status: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 80,
    accept_language: str | None = None,
) -> list[dict[str, Any]]:
    uid = uuid.UUID(principal.user_id)
    prefs = await session.get(UserPreferences, uid)
    lang = resolve_lang(prefs.language if prefs else None, accept_language)
    events: list[dict[str, Any]] = []
    types = get_artifact_registry().types

    tasks_q = select(Task).where(Task.user_id == uid, Task.origin == "interactive")
    if project_id:
        tasks_q = tasks_q.where(Task.project_id == uuid.UUID(project_id))
    if status:
        tasks_q = tasks_q.where(Task.status == status)
    if skill_id:
        tasks_q = tasks_q.where(Task.id.in_(select(TaskStep.task_id).where(TaskStep.skill_id == skill_id)))
    if since:
        tasks_q = tasks_q.where(Task.created_at >= since)
    if until:
        tasks_q = tasks_q.where(Task.created_at <= until)
    tasks = (await session.scalars(tasks_q.order_by(Task.created_at.desc()).limit(limit))).all() if not artifact_id else []
    skills = get_skill_registry()
    for task in tasks:
        names = [_skill_name(skills.get(s.skill_id), lang) for s in task.steps if s.skill_id and skills.has(s.skill_id)]
        base = {
            "category": "work",
            "system": "NOVA",
            "task_id": str(task.id),
            "project_id": str(task.project_id) if task.project_id else None,
            "conversation_id": str(task.conversation_id) if task.conversation_id else None,
            "skills": names,
        }
        events.append(
            {
                **base,
                "kind": "task_started",
                "at": task.created_at.isoformat(),
                "text": tr(lang, "started_with", skills=" → ".join(names)) if names else tr(lang, "started"),
                "detail": task.objective[:160],
                "status": "running",
            }
        )
        if task.finished_at:
            events.append(
                {
                    **base,
                    "kind": f"task_{task.status}",
                    "at": task.finished_at.isoformat(),
                    "status": task.status,
                    "text": (
                        tr(lang, task.status) if task.status in ("completed", "failed", "cancelled", "paused") else task.status
                    )
                    + (f" · {' → '.join(names)}" if names else ""),
                    "detail": task.objective[:160],
                }
            )

    members = select(ProjectMember.project_id).where(ProjectMember.user_id == uid)
    versions_q = (
        select(ArtifactVersion, Artifact)
        .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
        .where(or_(Artifact.owner_id == uid, Artifact.project_id.in_(members)), ArtifactVersion.state != "rejected")
    )
    if project_id:
        versions_q = versions_q.where(Artifact.project_id == uuid.UUID(project_id))
    if artifact_id:
        versions_q = versions_q.where(Artifact.id == uuid.UUID(artifact_id))
    if since:
        versions_q = versions_q.where(ArtifactVersion.created_at >= since)
    if until:
        versions_q = versions_q.where(ArtifactVersion.created_at <= until)
    if not (status or skill_id):
        for version, artifact in (
            await session.execute(versions_q.order_by(ArtifactVersion.created_at.desc()).limit(limit))
        ).all():
            name = types[artifact.type].localized_name(lang) if artifact.type in types else artifact.type
            who = "NOVA" if version.author_type == "nova" else tr(lang, "you")
            verb = "created" if version.version == 1 else ("proposed" if version.state == "proposed" else "updated")
            events.append(
                {
                    "kind": "artifact",
                    "category": "artifact",
                    "system": "NOVA" if version.author_type == "nova" else "You",
                    "author": version.author_type,
                    "at": version.created_at.isoformat(),
                    "artifact_id": str(artifact.id),
                    "project_id": str(artifact.project_id) if artifact.project_id else None,
                    "text": tr(lang, f"artifact_{verb}", who=who, title=artifact.title, version=version.version),
                    "detail": name,
                }
            )

    if not (artifact_id or status or skill_id):
        refs_q = select(ContextRetrievalReference).where(ContextRetrievalReference.user_id == uid)
        if since:
            refs_q = refs_q.where(ContextRetrievalReference.created_at >= since)
        for ref in (await session.scalars(refs_q.order_by(ContextRetrievalReference.created_at.desc()).limit(limit))).all():
            if project_id and ref.task_id is None:
                continue
            titles = [str(i.get("title")) for i in (ref.items or []) if isinstance(i, dict) and i.get("title")]
            count = len(ref.items)
            shown = tr(lang, "and_more", shown=", ".join(titles[:2]), n=count - 2) if count > 2 else ", ".join(titles[:2])
            events.append(
                {
                    "kind": "context",
                    "category": "context",
                    "system": "ORBIT" if ref.system == "orbit" else ref.system.upper(),
                    "at": ref.created_at.isoformat(),
                    "task_id": str(ref.task_id) if ref.task_id else None,
                    "text": tr(lang, "retrieved_one", title=titles[0])
                    if count == 1 and titles
                    else tr(lang, "retrieved_other", n=count),
                    "detail": shown if count > 1 else (ref.project_slug or ""),
                    "classification": ref.max_classification,
                }
            )

        # FORGE: evaluations of the user's executions (the learning end of the chain).
        evals_q = select(IntegrationReference).where(
            IntegrationReference.system == "forge",
            IntegrationReference.kind == "evaluation",
            IntegrationReference.nova_type == "task",
        )
        if since:
            evals_q = evals_q.where(IntegrationReference.updated_at >= since)
        own = {
            str(t)
            for t in (
                await session.scalars(select(Task.id).where(Task.user_id == uid).order_by(Task.created_at.desc()).limit(200))
            ).all()
        }
        for ref in (await session.scalars(evals_q.order_by(IntegrationReference.updated_at.desc()).limit(limit))).all():
            if ref.nova_id not in own:
                continue
            data = ref.data or {}
            score = data.get("composite_score")
            events.append(
                {
                    "kind": "evaluation",
                    "category": "quality",
                    "system": "FORGE",
                    "at": ref.updated_at.isoformat(),
                    "task_id": ref.nova_id,
                    "text": tr(lang, "forge_evaluated") if score is not None else tr(lang, "forge_queued"),
                    "detail": tr(lang, "score", score=round(float(score)))
                    + (f" · {tr(lang, 'passed')}" if data.get("passed") else "")
                    if score is not None
                    else (data.get("status") or ""),
                    "href": data.get("url"),
                }
            )

    if not (skill_id or status):
        # Decisions: what the user approved, rejected or confirmed (recorded in the audit log).
        decisions_q = select(AuditEvent).where(
            AuditEvent.actor_id == uid,
            AuditEvent.action.in_(("execution.approval", "execution.confirm_workflow", "artifact.status")),
        )
        if project_id:
            decisions_q = decisions_q.where(AuditEvent.project_id == uuid.UUID(project_id))
        if artifact_id:
            decisions_q = decisions_q.where(AuditEvent.target_type == "artifact", AuditEvent.target_id == artifact_id)
        if since:
            decisions_q = decisions_q.where(AuditEvent.created_at >= since)
        if until:
            decisions_q = decisions_q.where(AuditEvent.created_at <= until)
        decisions = [
            _decision(row, lang)
            for row in (await session.scalars(decisions_q.order_by(AuditEvent.created_at.desc()).limit(limit))).all()
        ]
        task_ids = {uuid.UUID(d["task_id"]) for d in decisions if d["task_id"]}
        decided = (
            {t.id: t for t in (await session.scalars(select(Task).where(Task.id.in_(task_ids), Task.user_id == uid))).all()}
            if task_ids
            else {}
        )
        for d in decisions:
            task = decided.get(uuid.UUID(d["task_id"])) if d["task_id"] else None
            if task is not None:
                d["detail"] = task.objective[:160]
                d["conversation_id"] = str(task.conversation_id) if task.conversation_id else None
        events.extend(decisions)

    names = dict((await session.execute(select(Project.id, Project.name))).all()) if events else {}
    for event in events:
        pid = event.get("project_id")
        event["project_name"] = names.get(uuid.UUID(pid)) if pid else None
    events.sort(key=lambda e: e["at"], reverse=True)
    return events[:limit]


def _skill_name(spec: Any, lang: Lang) -> str:
    return str(spec.translations.get(lang, {}).get("name") or spec.name)


def _decision(row: AuditEvent, lang: Lang = "en") -> dict[str, Any]:
    value = (row.details or {}).get("value") or {}
    action = str(value.get("action") or (row.details or {}).get("to") or "")
    if row.action == "artifact.status":
        status = tr(lang, f"status_{action}") if f"status_{action}" in MESSAGES else action.replace("_", " ")
        text = tr(lang, "decision_status", title=row.summary.split(":", 1)[0], status=status)
    elif row.action == "execution.confirm_workflow":
        text = tr(lang, "decision_cancel_workflow" if action == "cancel" else "decision_confirm_workflow")
    else:
        text = tr(lang, {"approve": "decision_approve", "reject": "decision_reject"}.get(action, "decision_other"))
    return {
        "kind": "decision",
        "category": "decision",
        "system": "You",
        "at": row.created_at.isoformat(),
        "text": text,
        "detail": "",
        "status": action,
        "task_id": row.target_id if row.target_type == "task" else None,
        "artifact_id": row.target_id if row.target_type == "artifact" else None,
        "project_id": str(row.project_id) if row.project_id else None,
    }


async def search(
    session: AsyncSession, principal: Principal, q: str, *, include_context: bool = True
) -> dict[str, list[dict[str, Any]]]:
    uid = uuid.UUID(principal.user_id)
    like = f"%{q[:100]}%"
    members = select(ProjectMember.project_id).where(ProjectMember.user_id == uid)
    projects = (await session.scalars(select(Project).where(Project.id.in_(members), Project.name.ilike(like)).limit(5))).all()
    artifacts = (
        await session.scalars(
            select(Artifact)
            .where(or_(Artifact.owner_id == uid, Artifact.project_id.in_(members)), Artifact.title.ilike(like))
            .order_by(Artifact.updated_at.desc())
            .limit(8)
        )
    ).all()
    conversations = (
        await session.scalars(
            select(Conversation)
            .where(Conversation.user_id == uid, Conversation.title.ilike(like))
            .order_by(Conversation.updated_at.desc())
            .limit(6)
        )
    ).all()
    needle = q.lower()
    skills = [
        s
        for s in get_skill_registry().all(include_system=False)
        if needle in s.name.lower() or needle in s.summary.lower() or any(needle in t for t in s.triggers)
    ][:6]
    context: list[dict[str, Any]] = []
    context_error = None
    if include_context and len(q) >= 3:
        refs = (
            await session.execute(
                select(ProjectReference.external_id, Project.id)
                .join(Project, Project.id == ProjectReference.project_id)
                .where(ProjectReference.system == "orbit", Project.id.in_(members))
                .limit(3)
            )
        ).all()
        for slug, pid in refs:
            try:
                for hit in await providers.context().search(principal.user_id, slug, q, 4):
                    context.append({**hit.model_dump(mode="json"), "project_id": str(pid)})
            except ContextError as exc:
                context_error = exc.message
    return {
        "projects": [{"id": str(p.id), "name": p.name, "description": p.description[:120]} for p in projects],
        "artifacts": [{"id": str(a.id), "title": a.title, "type": a.type} for a in artifacts],
        "conversations": [{"id": str(c.id), "title": c.title} for c in conversations],
        "skills": [{"id": s.id, "name": s.name, "summary": s.summary, "translations": s.translations} for s in skills],
        "context": context,
        "context_error": [{"message": context_error}] if context_error else [],
    }
