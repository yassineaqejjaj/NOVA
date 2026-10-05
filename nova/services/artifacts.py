"""Artifacts: create, edit (autosave with optimistic concurrency), versions, compare, comments, export, provenance."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.artifacts.registry import get_artifact_registry
from nova.artifacts.render import render_markdown
from nova.domain.artifacts import (
    ArtifactContent,
    SectionContent,
    apply_section_updates,
    compare_contents,
    empty_content,
)
from nova.domain.context import ContextItem
from nova.domain.enums import ProjectRole
from nova.domain.permissions import Principal
from nova.infra.db import aware, utcnow
from nova.infra.models import (
    Artifact,
    ArtifactComment,
    ArtifactVersion,
    ContextRetrievalReference,
    IntegrationReference,
    ProjectMember,
    SkillExecution,
    TaskStep,
    User,
)
from nova.services.access import AccessDenied, project_role, require_artifact
from nova.services.audit import audit


class VersionConflict(Exception):
    def __init__(self, current: int) -> None:
        super().__init__(f"Artifact changed (current version {current})")
        self.current = current


def summary(a: Artifact) -> dict[str, Any]:
    t = get_artifact_registry().types.get(a.type)
    return {
        "id": str(a.id),
        "type": a.type,
        "type_name": t.name if t else a.type,
        "icon": t.icon if t else "file-text",
        "title": a.title,
        "status": a.status,
        "project_id": str(a.project_id) if a.project_id else None,
        "version": a.current_version,
        "classification": a.classification,
        "owner_id": str(a.owner_id),
        "conversation_id": str(a.conversation_id) if a.conversation_id else None,
        "task_id": str(a.task_id) if a.task_id else None,
        "created_at": aware(a.created_at).isoformat(),
        "updated_at": aware(a.updated_at).isoformat(),
    }


async def _version(session: AsyncSession, artifact_id: uuid.UUID, version: int) -> ArtifactVersion:
    row = await session.scalar(
        select(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact_id, ArtifactVersion.version == version)
    )
    if row is None:
        raise AccessDenied
    return row


async def list_artifacts(
    session: AsyncSession,
    principal: Principal,
    *,
    project_id: str | None = None,
    type_: str | None = None,
    q: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    uid = uuid.UUID(principal.user_id)
    member_projects = select(ProjectMember.project_id).where(ProjectMember.user_id == uid)
    query = select(Artifact).where(
        or_(Artifact.owner_id == uid, Artifact.project_id.in_(member_projects)), Artifact.status != "archived"
    )
    if project_id:
        query = query.where(Artifact.project_id == uuid.UUID(project_id))
    if type_:
        query = query.where(Artifact.type == type_)
    if q:
        query = query.where(Artifact.title.ilike(f"%{q[:100]}%"))
    rows = (await session.scalars(query.order_by(Artifact.updated_at.desc()).limit(limit))).all()
    return [summary(a) for a in rows]


async def get_artifact(
    session: AsyncSession, principal: Principal, artifact_id: str, version: int | None = None
) -> dict[str, Any]:
    artifact, role = await require_artifact(session, artifact_id, principal)
    row = await _version(session, artifact.id, version or artifact.current_version)
    proposed = await session.scalar(
        select(ArtifactVersion.version)
        .where(ArtifactVersion.artifact_id == artifact.id, ArtifactVersion.state == "proposed")
        .order_by(ArtifactVersion.version.desc())
    )
    evaluation = None
    if artifact.task_id:
        ref = await session.scalar(
            select(IntegrationReference).where(
                IntegrationReference.system == "forge",
                IntegrationReference.kind == "evaluation",
                IntegrationReference.nova_type == "task",
                IntegrationReference.nova_id == str(artifact.task_id),
            )
        )
        evaluation = ref.data if ref else None
    artifact_type = get_artifact_registry().get(artifact.type)
    content = ArtifactContent.model_validate(row.content)
    sources = await _sources(session, principal, content.citations())
    # NOVA confidence: the Validation agent's report of the step that produced it, and FORGE's score when known
    report = await session.scalar(
        select(TaskStep.report)
        .where(TaskStep.artifact_id == artifact.id)
        .order_by(TaskStep.finished_at.desc().nulls_last())
        .limit(1)
    )
    score = (evaluation or {}).get("composite_score")
    from nova.services.inbox import confidence_from_report

    confidence = confidence_from_report(report, float(score) if isinstance(score, int | float) else None)
    return {
        **summary(artifact),
        "role": role.value,
        "evidence": await _evidence(session, artifact, sources),
        "quality": await _quality(session, artifact, row, content, sources, evaluation),
        "can_edit": role in (ProjectRole.owner, ProjectRole.editor),
        "viewing_version": row.version,
        "version_state": row.state,
        "proposed_version": proposed,
        "content": row.content,
        "definition": artifact_type.model_dump(mode="json"),
        "evaluation": evaluation,
        "confidence": confidence,
    }


async def create_artifact(
    session: AsyncSession, principal: Principal, *, type_: str, title: str, project_id: str | None
) -> dict[str, Any]:
    artifact_type = get_artifact_registry().get(type_)
    pid = uuid.UUID(project_id) if project_id else None
    if pid and (await project_role(session, pid, uuid.UUID(principal.user_id))) not in (ProjectRole.owner, ProjectRole.editor):
        raise AccessDenied
    artifact = Artifact(type=type_, title=title[:300], project_id=pid, owner_id=uuid.UUID(principal.user_id), current_version=1)
    session.add(artifact)
    await session.flush()
    content = empty_content(artifact_type, title[:300])
    session.add(
        ArtifactVersion(
            artifact_id=artifact.id,
            version=1,
            content=content.model_dump(mode="json"),
            changed_sections=[],
            author_type="user",
            author_id=uuid.UUID(principal.user_id),
            summary="Created",
            state="current",
        )
    )
    await audit(
        session,
        actor_id=principal.user_id,
        action="artifact.create",
        target_type="artifact",
        target_id=str(artifact.id),
        project_id=pid,
        summary=f"Created {artifact_type.name} '{title[:80]}'",
    )
    return summary(artifact)


async def save_user_edit(
    session: AsyncSession,
    principal: Principal,
    artifact_id: str,
    *,
    base_version: int,
    sections: dict[str, Any] | None,
    title: str | None,
    status: str | None,
) -> dict[str, Any]:
    """Autosave: a new immutable version per save; refuses to overwrite a newer version (409)."""
    artifact, _ = await require_artifact(session, artifact_id, principal, ProjectRole.editor)
    if base_version != artifact.current_version:
        raise VersionConflict(artifact.current_version)
    artifact_type = get_artifact_registry().get(artifact.type)
    current = ArtifactContent.model_validate((await _version(session, artifact.id, artifact.current_version)).content)
    updates = {k: SectionContent.model_validate(v) for k, v in (sections or {}).items()}
    content, changed = apply_section_updates(current, updates, artifact_type)
    if title and title.strip() and title.strip() != content.title:
        content = content.model_copy(update={"title": title.strip()[:300]})
        artifact.title = content.title
        changed.append("title")
    if status in ("draft", "in_review", "final", "archived") and status != artifact.status:
        await audit(
            session,
            actor_id=principal.user_id,
            action="artifact.status",
            target_type="artifact",
            target_id=str(artifact.id),
            project_id=artifact.project_id,
            summary=f"{artifact.title}: {artifact.status} → {status}",
            details={"from": artifact.status, "to": status},
        )
        artifact.status = status
    if not changed:
        return {"version": artifact.current_version, "changed_sections": []}
    version = artifact.current_version + 1
    old = await _version(session, artifact.id, artifact.current_version)
    old.state = "superseded"
    session.add(
        ArtifactVersion(
            artifact_id=artifact.id,
            version=version,
            content=content.model_dump(mode="json"),
            changed_sections=changed,
            author_type="user",
            author_id=uuid.UUID(principal.user_id),
            summary="Edited " + ", ".join(changed)[:200],
            state="current",
        )
    )
    artifact.current_version = version
    artifact.updated_at = utcnow()
    await session.flush()
    return {"version": version, "changed_sections": changed}


async def _evidence(session: AsyncSession, artifact: Artifact, sources: list[dict[str, Any]]) -> dict[str, Any]:
    """What the Artifact is grounded on: cited sources grouped by type (real citations only)."""
    by_type: dict[str, int] = {}
    for source in sources:
        by_type[source.get("type") or "source"] = by_type.get(source.get("type") or "source", 0) + 1
    updated = None
    if artifact.task_id:
        updated = await session.scalar(
            select(ContextRetrievalReference.created_at)
            .where(ContextRetrievalReference.task_id == artifact.task_id)
            .order_by(ContextRetrievalReference.created_at.desc())
        )
    return {
        "sources_count": len(sources),
        "updated_at": updated.isoformat() if updated else None,
        "by_type": [{"type": t, "count": n} for t, n in sorted(by_type.items(), key=lambda kv: -kv[1])],
        "sources": sources[:12],
    }


async def _quality(session: AsyncSession, artifact: Artifact, row: ArtifactVersion, content: ArtifactContent,
                   sources: list[dict[str, Any]], evaluation: dict[str, Any] | None) -> list[dict[str, str]]:  # fmt: skip
    """Deterministic quality checks (status pass | warn | pending), never an invented score."""
    checks: list[dict[str, str]] = []
    cited = len({(c.ref, c.label) for c in content.citations()})
    checks.append({
        "key": "grounded", "label": "Grounded in sources",
        "status": "pass" if sources else "warn",
        "detail": f"{len(sources)} source{'s' if len(sources) != 1 else ''} cited" if sources
        else ("Citations no longer resolvable" if cited else "No source cited"),
    })  # fmt: skip
    dropped = None
    if row.skill_execution_id:
        output = await session.scalar(select(SkillExecution.output).where(SkillExecution.id == row.skill_execution_id))
        dropped = (output or {}).get("dropped_citations")
    if dropped is not None:
        checks.append({
            "key": "unsupported", "label": "No unsupported claims",
            "status": "pass" if dropped == 0 else "warn",
            "detail": "Every citation matches a served source" if dropped == 0 else f"{dropped} unverifiable citation(s) removed by NOVA",
        })  # fmt: skip
    artifact_type = get_artifact_registry().get(artifact.type)
    empty = [s.title for s in artifact_type.sections if (sec := content.sections.get(s.key)) is None or sec.is_empty()]
    checks.append({
        "key": "complete", "label": "All sections drafted",
        "status": "pass" if not empty else "warn",
        "detail": "Complete" if not empty else f"{len(empty)} empty: {', '.join(empty[:3])}{'…' if len(empty) > 3 else ''}",
    })  # fmt: skip
    stories = [i for _, i in content.all_items() if i.kind == "story"]
    if stories:
        missing = sum(1 for i in stories if not i.attributes.get("acceptance_criteria"))
        checks.append({
            "key": "acceptance", "label": "Stories have acceptance criteria",
            "status": "pass" if not missing else "warn",
            "detail": f"{len(stories)} stories" if not missing else f"{missing} of {len(stories)} missing",
        })  # fmt: skip
    if evaluation:
        passed = evaluation.get("passed")
        score = evaluation.get("composite_score")
        checks.append({
            "key": "forge", "label": "Consistent with context (FORGE)",
            "status": "pass" if passed else ("warn" if passed is False else "pending"),
            "detail": f"Score {round(score)}" if score is not None else f"Evaluation {evaluation.get('status') or 'queued'}",
        })  # fmt: skip
    return checks


async def list_versions(session: AsyncSession, principal: Principal, artifact_id: str) -> list[dict[str, Any]]:
    artifact, _ = await require_artifact(session, artifact_id, principal)
    rows = (
        await session.execute(
            select(ArtifactVersion, User.display_name, SkillExecution.skill_id, SkillExecution.skill_version)
            .outerjoin(User, User.id == ArtifactVersion.author_id)
            .outerjoin(SkillExecution, SkillExecution.id == ArtifactVersion.skill_execution_id)
            .where(ArtifactVersion.artifact_id == artifact.id)
            .order_by(ArtifactVersion.version.desc())
        )
    ).all()
    return [
        {
            "version": v.version,
            "state": v.state,
            "author_type": v.author_type,
            "author_name": name or ("NOVA" if v.author_type == "nova" else None),
            "skill_id": skill_id,
            "skill_version": skill_version,
            "changed_sections": v.changed_sections,
            "summary": v.summary,
            "task_id": str(v.task_id) if v.task_id else None,
            "created_at": aware(v.created_at).isoformat(),
        }
        for v, name, skill_id, skill_version in rows
    ]


async def compare(session: AsyncSession, principal: Principal, artifact_id: str, v_from: int, v_to: int) -> dict[str, Any]:
    artifact, _ = await require_artifact(session, artifact_id, principal)
    old = ArtifactContent.model_validate((await _version(session, artifact.id, v_from)).content)
    new = ArtifactContent.model_validate((await _version(session, artifact.id, v_to)).content)
    return {"from": v_from, "to": v_to, "sections": [d.model_dump() for d in compare_contents(old, new)]}


async def comments(session: AsyncSession, principal: Principal, artifact_id: str) -> list[dict[str, Any]]:
    artifact, _ = await require_artifact(session, artifact_id, principal)
    rows = (
        await session.execute(
            select(ArtifactComment, User.display_name)
            .join(User, User.id == ArtifactComment.author_id)
            .where(ArtifactComment.artifact_id == artifact.id)
            .order_by(ArtifactComment.created_at)
        )
    ).all()
    return [
        {
            "id": str(c.id),
            "section_key": c.section_key,
            "item_id": c.item_id,
            "author_name": name,
            "body": c.body,
            "resolved": c.resolved,
            "created_at": aware(c.created_at).isoformat(),
        }
        for c, name in rows
    ]


async def add_comment(
    session: AsyncSession, principal: Principal, artifact_id: str, *, section_key: str, item_id: str | None, body: str
) -> dict[str, Any]:
    artifact, _ = await require_artifact(session, artifact_id, principal)
    if get_artifact_registry().get(artifact.type).section(section_key) is None:
        raise AccessDenied
    comment = ArtifactComment(
        artifact_id=artifact.id,
        section_key=section_key,
        item_id=item_id,
        author_id=uuid.UUID(principal.user_id),
        body=body[:4000],
    )
    session.add(comment)
    await session.flush()
    return {"id": str(comment.id)}


async def resolve_comment(session: AsyncSession, principal: Principal, artifact_id: str, comment_id: str) -> None:
    artifact, _ = await require_artifact(session, artifact_id, principal)
    comment = await session.get(ArtifactComment, uuid.UUID(comment_id))
    if comment is None or comment.artifact_id != artifact.id:
        raise AccessDenied
    comment.resolved = True


async def export(session: AsyncSession, principal: Principal, artifact_id: str, fmt: str) -> tuple[str, str, str]:
    artifact, _ = await require_artifact(session, artifact_id, principal)
    content = ArtifactContent.model_validate((await _version(session, artifact.id, artifact.current_version)).content)
    filename = "".join(ch if ch.isalnum() else "-" for ch in artifact.title.lower()).strip("-")[:80] or "artifact"
    if fmt == "json":
        return content.model_dump_json(indent=2), "application/json", f"{filename}.json"
    sources = [
        {"label": s["label"], "title": s["title"], "uri": s.get("uri")}
        for s in await _sources(session, principal, content.citations())
    ]
    return (
        render_markdown(content, get_artifact_registry().get(artifact.type), sources=sources),
        "text/markdown",
        f"{filename}.md",
    )


async def _sources(session: AsyncSession, principal: Principal, citations: list) -> list[dict[str, Any]]:
    ref_ids = sorted({c.ref for c in citations if c.ref})
    if not ref_ids:
        return []
    refs = (
        await session.scalars(
            select(ContextRetrievalReference).where(
                ContextRetrievalReference.id.in_([uuid.UUID(r) for r in ref_ids]),
                ContextRetrievalReference.user_id == uuid.UUID(principal.user_id) if not principal.is_admin else True,
            )
        )
    ).all()
    by_key = {(str(r.id), i["citation"]): ContextItem.model_validate(i) for r in refs for i in r.items}
    result, seen = [], set()
    for c in citations:
        item = by_key.get((c.ref or "", c.label))
        if item and (c.ref, c.label) not in seen:
            seen.add((c.ref, c.label))
            result.append(
                {
                    "label": c.label,
                    "reference_id": c.ref,
                    "title": item.title,
                    "uri": item.uri,
                    "type": item.memory_kind or item.source_kind,
                    "classification": item.classification,
                    "updated": item.date.isoformat() if item.date else None,
                    "excerpt": item.excerpt[:400],
                    "project": item.project_slug,
                }
            )
    return result


async def provenance(
    session: AsyncSession, principal: Principal, artifact_id: str, *, section_key: str | None, item_id: str | None
) -> dict[str, Any]:
    """Recorded provenance of an item / section / the whole Artifact (deterministic, no model call)."""
    artifact, _ = await require_artifact(session, artifact_id, principal)
    content = ArtifactContent.model_validate((await _version(session, artifact.id, artifact.current_version)).content)
    rationale = ""
    if item_id and (found := content.find_item(item_id)):
        citations, rationale = found[1].citations, found[1].rationale
    elif section_key and (section := content.sections.get(section_key)):
        citations = [c for b in section.blocks for c in b.citations] + [c for i in section.items for c in i.citations]
    else:
        citations = content.citations()
    # Which Skill execution introduced it: the earliest NOVA version that contains the item.
    origin = None
    versions = (
        await session.execute(
            select(
                ArtifactVersion.version,
                ArtifactVersion.content,
                SkillExecution.skill_id,
                SkillExecution.skill_version,
                ArtifactVersion.created_at,
            )
            .outerjoin(SkillExecution, SkillExecution.id == ArtifactVersion.skill_execution_id)
            .where(ArtifactVersion.artifact_id == artifact.id)
            .order_by(ArtifactVersion.version)
        )
    ).all()
    for version, raw, skill_id, skill_version, created in versions:
        if item_id is None or ArtifactContent.model_validate(raw).find_item(item_id):
            origin = {"version": version, "skill_id": skill_id, "skill_version": skill_version, "created_at": created.isoformat()}
            break
    return {
        "sources": await _sources(session, principal, citations),
        "rationale": rationale,
        "origin": origin,
        "unresolved": len([c for c in citations if not c.ref]),
    }
