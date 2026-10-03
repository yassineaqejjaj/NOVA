"""Projects organize NOVA work; ORBIT-linked projects mirror the user's ORBIT membership (ACL propagation)."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.config import get_settings
from nova.domain.context import ContextError
from nova.domain.enums import ProjectRole
from nova.domain.permissions import Principal
from nova.infra.models import Artifact, Project, ProjectMember, ProjectReference, Task, User
from nova.services import providers
from nova.services.access import AccessDenied, project_role
from nova.services.audit import audit

ORBIT_ROLE = {"owner": ProjectRole.owner, "editor": ProjectRole.editor, "viewer": ProjectRole.viewer}


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:100] or "project"


def project_view(p: Project, role: str | None, stats: dict[str, int] | None = None) -> dict[str, Any]:
    orbit = next((r for r in p.references if r.system == "orbit"), None)
    return {
        "id": str(p.id),
        "slug": p.slug,
        "name": p.name,
        "description": p.description,
        "role": role,
        "orbit_slug": orbit.external_id if orbit else None,
        "orbit_url": orbit.url if orbit else None,
        "stats": stats or {},
        "updated_at": p.updated_at.isoformat(),
    }


async def list_projects(session: AsyncSession, principal: Principal) -> list[dict[str, Any]]:
    uid = uuid.UUID(principal.user_id)
    rows = (
        await session.execute(
            select(Project, ProjectMember.role)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == uid)
            .order_by(Project.name)
        )
    ).all()
    result = []
    for project, role in rows:
        artifacts = await session.scalar(select(func.count()).select_from(Artifact).where(Artifact.project_id == project.id)) or 0
        active = (
            await session.scalar(
                select(func.count())
                .select_from(Task)
                .where(Task.project_id == project.id, Task.status.in_(["queued", "running", "waiting_user"]))
            )
            or 0
        )
        result.append(project_view(project, role, {"artifacts": artifacts, "active_work": active}))
    return result


async def sync_from_orbit(session: AsyncSession, principal: Principal) -> int:
    """Mirror the ORBIT projects the user belongs to (role inherited). Raises ContextError if ORBIT is unavailable."""
    infos = await providers.context().list_projects(principal.user_id)
    uid = uuid.UUID(principal.user_id)
    seen: set[uuid.UUID] = set()
    for info in infos:
        ref = await session.scalar(
            select(ProjectReference).where(ProjectReference.system == "orbit", ProjectReference.external_id == info.slug)
        )
        if ref is None:
            slug = info.slug
            if await session.scalar(select(Project.id).where(Project.slug == slug)):
                slug = f"{slug}-{uuid.uuid4().hex[:4]}"
            project = Project(slug=slug, name=info.name, description=info.description, created_by=uid)
            session.add(project)
            await session.flush()
            session.add(
                ProjectReference(
                    project_id=project.id,
                    system="orbit",
                    external_id=info.slug,
                    label=info.name,
                    url=f"{get_settings().orbit_public_url.rstrip('/')}/projects/{info.slug}",
                )
            )
            project_id = project.id
        else:
            project_id = ref.project_id
        seen.add(project_id)
        role = ORBIT_ROLE.get(info.role or "viewer", ProjectRole.viewer).value
        member = await session.get(ProjectMember, (project_id, uid))
        if member is None:
            session.add(ProjectMember(project_id=project_id, user_id=uid, role=role, source="orbit"))
        elif member.source == "orbit":
            member.role = role
    # Membership synced from ORBIT disappears when ORBIT no longer grants it.
    for member in (
        await session.scalars(select(ProjectMember).where(ProjectMember.user_id == uid, ProjectMember.source == "orbit"))
    ).all():
        if member.project_id not in seen:
            await session.delete(member)
    await session.flush()
    return len(infos)


async def create_project(session: AsyncSession, principal: Principal, *, name: str, description: str) -> dict[str, Any]:
    slug = _slugify(name)
    if await session.scalar(select(Project.id).where(Project.slug == slug)):
        slug = f"{slug}-{uuid.uuid4().hex[:4]}"
    project = Project(slug=slug, name=name[:200], description=description[:2000], created_by=uuid.UUID(principal.user_id))
    session.add(project)
    await session.flush()
    session.add(ProjectMember(project_id=project.id, user_id=uuid.UUID(principal.user_id), role="owner", source="nova"))
    await audit(
        session,
        actor_id=principal.user_id,
        action="project.create",
        target_type="project",
        target_id=str(project.id),
        project_id=project.id,
        summary=f"Created project {name[:80]}",
    )
    await session.flush()
    await session.refresh(project)
    return project_view(project, "owner")


async def project_detail(session: AsyncSession, principal: Principal, project_id: str) -> dict[str, Any]:
    pid = uuid.UUID(project_id)
    role = await project_role(session, pid, uuid.UUID(principal.user_id))
    if role is None and not principal.is_admin:
        raise AccessDenied
    project = await session.get(Project, pid)
    if project is None:
        raise AccessDenied
    members = (
        await session.execute(
            select(User.display_name, User.title, ProjectMember.role)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == pid)
        )
    ).all()
    view = project_view(project, role.value if role else "owner")
    view["people"] = [{"name": n, "title": t, "role": r} for n, t, r in members]
    orbit_slug = view["orbit_slug"]
    view["decisions"], view["context_error"] = [], None
    if orbit_slug:
        try:
            changes = await providers.context().recent_changes(principal.user_id, orbit_slug, None)
            view["decisions"] = [
                c.model_dump(mode="json")
                for c in changes
                # Key insights: everything validated in ORBIT, plus newly recorded decisions.
                if c.type == "memory.validated"
                or (c.type == "memory.created" and (c.data or {}).get("kind", "decision") == "decision")
            ][:8]
            view["recent_context"] = [c.model_dump(mode="json") for c in changes][:10]
        except ContextError as exc:
            view["context_error"] = {"code": exc.code, "message": exc.message}
    return view
