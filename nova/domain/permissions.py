"""Permissions, RBAC and autonomy policy.

Personal preferences can make NOVA *more* cautious than the organization policy, never less.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from nova.domain.enums import AutonomyMode, ProjectRole, role_at_least


class Permission(StrEnum):
    context_read = "context.read"
    context_write_external = "context.write_external"  # propose memory / publish to ORBIT
    artifact_read = "artifact.read"
    artifact_write = "artifact.write"
    task_execute = "task.execute"
    project_manage = "project.manage"
    admin = "admin"


PROJECT_ROLE_PERMISSIONS: dict[ProjectRole, frozenset[Permission]] = {
    ProjectRole.viewer: frozenset({Permission.context_read, Permission.artifact_read}),
    ProjectRole.editor: frozenset(
        {
            Permission.context_read,
            Permission.artifact_read,
            Permission.artifact_write,
            Permission.task_execute,
            Permission.context_write_external,
        }
    ),
    ProjectRole.owner: frozenset(set(Permission) - {Permission.admin}),
}


@dataclass(frozen=True, slots=True)
class Principal:
    """Authenticated NOVA user."""

    user_id: str
    email: str
    display_name: str
    realm_roles: frozenset[str] = field(default_factory=frozenset)
    is_admin: bool = False
    is_service: bool = False  # FORGE protocol / scheduler


def project_permissions(role: ProjectRole | None, principal: Principal) -> frozenset[Permission]:
    if principal.is_admin:
        return frozenset(Permission)
    if role is None:
        return frozenset()
    return PROJECT_ROLE_PERMISSIONS[role]


def can(principal: Principal, permission: Permission, role: ProjectRole | None) -> bool:
    return permission in project_permissions(role, principal)


def can_read_project(principal: Principal, role: ProjectRole | None) -> bool:
    return principal.is_admin or role_at_least(role, ProjectRole.viewer)


@dataclass(frozen=True, slots=True)
class AutonomyPolicy:
    """Effective autonomy for one execution."""

    mode: AutonomyMode
    allow_auto_external_writes: bool  # organization policy

    @classmethod
    def resolve(
        cls, requested: AutonomyMode | None, user_default: AutonomyMode | None, *, org_allows_auto_external_writes: bool
    ) -> AutonomyPolicy:
        return cls(
            mode=requested or user_default or AutonomyMode.assist,
            allow_auto_external_writes=org_allows_auto_external_writes,
        )

    def confirm_workflow(self, step_count: int) -> bool:
        """Should NOVA show the proposed workflow and wait before executing it?"""
        if self.mode == AutonomyMode.suggest:
            return True
        if self.mode == AutonomyMode.assist:
            return step_count >= 2
        return False

    def approve_artifact_changes(self, *, editing_existing: bool) -> bool:
        """Should changes to an existing Artifact wait for approval before becoming current?"""
        return self.mode == AutonomyMode.execute_with_approval and editing_existing

    def approve_external_write(self) -> bool:
        """Any action modifying an external system requires approval unless the organization allows it."""
        return not (self.mode == AutonomyMode.execute_automatically and self.allow_auto_external_writes)
