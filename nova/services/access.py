"""Access control on NOVA objects (project roles, Artifact ownership)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.domain.enums import ProjectRole, role_at_least
from nova.domain.permissions import Permission, Principal, project_permissions
from nova.infra.models import Artifact, ProjectMember, Task


class AccessDenied(Exception):
    """Raised as 404 by the API (existence of inaccessible objects is not revealed)."""


async def project_role(session: AsyncSession, project_id: uuid.UUID | None, user_id: uuid.UUID) -> ProjectRole | None:
    if project_id is None:
        return None
    role = await session.scalar(
        select(ProjectMember.role).where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
    )
    return ProjectRole(role) if role else None


async def artifact_role(session: AsyncSession, artifact: Artifact, principal: Principal) -> ProjectRole | None:
    """Owner of the Artifact = owner role; otherwise the project role (if any)."""
    if principal.is_admin or str(artifact.owner_id) == principal.user_id:
        return ProjectRole.owner
    return await project_role(session, artifact.project_id, uuid.UUID(principal.user_id))


async def require_artifact(
    session: AsyncSession, artifact_id: uuid.UUID | str, principal: Principal, minimum: ProjectRole = ProjectRole.viewer
) -> tuple[Artifact, ProjectRole]:
    try:
        aid = artifact_id if isinstance(artifact_id, uuid.UUID) else uuid.UUID(str(artifact_id))
    except ValueError as exc:
        raise AccessDenied from exc
    artifact = await session.get(Artifact, aid)
    if artifact is None:
        raise AccessDenied
    role = await artifact_role(session, artifact, principal)
    if not role_at_least(role, minimum):
        raise AccessDenied
    return artifact, role  # type: ignore[return-value]


async def require_task(session: AsyncSession, task_id: uuid.UUID | str, principal: Principal) -> Task:
    try:
        tid = task_id if isinstance(task_id, uuid.UUID) else uuid.UUID(str(task_id))
    except ValueError as exc:
        raise AccessDenied from exc
    task = await session.get(Task, tid)
    if task is None or (str(task.user_id) != principal.user_id and not principal.is_admin):
        raise AccessDenied
    return task


async def effective_permissions(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID | None
) -> frozenset[Permission]:
    """Permissions for an execution: personal work (no project) gives full rights on one's own Artifacts."""
    if project_id is None:
        return frozenset({Permission.context_read, Permission.artifact_read, Permission.artifact_write, Permission.task_execute})
    role = await project_role(session, project_id, uuid.UUID(principal.user_id))
    return project_permissions(role, principal)
