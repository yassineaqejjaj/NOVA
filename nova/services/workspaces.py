"""Workspaces (``orion_workspace_id``) and ORION projects (``orion_project_id``): ADR 001 §5 and §9, NOV-107.

The mechanics of the filter live in ``nova.infra.scope``; this module is what the rest of NOVA calls: which workspace a
request belongs to, how the default workspace is registered, how checkpoint threads and capture keys carry the workspace,
and how a NOVA project is aligned with the ORION project ORBIT reports.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.config import get_settings
from nova.domain.orion_claims import Claims, ClaimsError, effective_clearance, parse_claims
from nova.domain.workspace import as_uuid, outbox_key, thread_id
from nova.infra.models import Project, ProjectReference, Workspace
from nova.infra.scope import default_workspace_id, mode

CLAIM = "orion_workspace_id"
#: The ORION project namespace of the projects that existed before ORION ids did (migration 0020, ``uuid5(ns, project id)``).
PROJECT_NAMESPACE = uuid.UUID("6f5c1a52-9f0e-4c1b-8d9a-0a1b2c3d4e5f")


class WorkspaceMismatch(Exception):
    """The token's workspace is not the one of the account it identifies."""


def strict() -> bool:
    """``NOVA_WORKSPACE_STRICT_CLAIM``: tokens are read through the ORION claims contract (nova/domain/orion_claims.py)."""
    return get_settings().workspace_strict_claim


def enabled() -> bool:
    """Is the workspace of a request read from the account / the token (``shadow``, ``enforce``, strict claims)?"""
    return mode() != "off" or strict()


class TokenRefused(Exception):
    """A validated token that the ORION claims contract refuses; ``code`` is the contract's stable error code."""

    def __init__(self, code: str, status: int = 401) -> None:
        super().__init__(code)
        self.code, self.status = code, status


def read_claims(payload: dict[str, Any]) -> Claims:
    """The ORION claims of a token whose signature, issuer, audience and times were already validated (strict only).

    A malformed ORION claim refuses the token (a bad ``orion_clearance`` is never read as "no cap"); a token without
    ``orion_workspace_id`` opens no workspace resource: every NOVA resource is one, so it is refused (403).
    """
    try:
        claims = parse_claims(payload)
    except ClaimsError as exc:
        raise TokenRefused(exc.code) from exc
    if claims.workspace_id is None:
        raise TokenRefused("workspace_required", 403)
    return claims


def capped_clearance(local: int, cap: int | None) -> int:
    """ADR §4: ``min(local clearance, orion_clearance)``; an absent claim never gives more than the local value."""
    return effective_clearance(local, cap)


def claim_of(claims: dict[str, Any]) -> uuid.UUID | None:
    """The ``orion_workspace_id`` claim of a *validated* token (ADR §3), or None when absent or not a UUID."""
    return as_uuid(claims.get(CLAIM)) if claims.get(CLAIM) else None


def workspace_of_request(account_workspace: uuid.UUID | None) -> uuid.UUID:
    """The workspace a request runs in: the account's own (copied from the token when it was created), else the default.

    With ``off`` it is always the default workspace: nothing reads a workspace until the filter is turned on.
    """
    if not enabled() or account_workspace is None:
        return default_workspace_id()
    return account_workspace


def check_token_workspace(account_workspace: uuid.UUID | None, token_workspace: uuid.UUID | None) -> None:
    """A token for another workspace than its account's never opens that account (``enforce``); counted in ``shadow``."""
    if not enabled() or token_workspace is None:
        return
    if token_workspace != (account_workspace or default_workspace_id()):
        from nova.infra.scope import record_shadow

        if mode() == "enforce" or strict():
            raise WorkspaceMismatch
        record_shadow("token", "users")


async def ensure_workspace(session: AsyncSession, workspace_id: uuid.UUID, name: str = "") -> Workspace:
    """Register a workspace id seen in a validated token (or the default one); never renames an existing one."""
    row = await session.get(Workspace, workspace_id)
    if row is None:
        row = Workspace(id=workspace_id, name=name)
        session.add(row)
        await session.flush()
    return row


async def ensure_default_workspace(session: AsyncSession) -> Workspace:
    return await ensure_workspace(session, default_workspace_id(), "Default workspace")


async def workspace_ids(session: AsyncSession) -> list[uuid.UUID]:
    """Every registered workspace (jobs that operate per workspace: retention, forget)."""
    return list((await session.scalars(select(Workspace.id).order_by(Workspace.created_at, Workspace.id))).all())


# --- Keys that must not collide between workspaces ---------------------------------------------------------------------------


def cache_key(*parts: Any) -> tuple[Any, ...]:
    """In-process cache key: the workspace of the running code comes first (the cache never serves another workspace)."""
    from nova.infra.scope import current_workspace

    return (current_workspace(), *parts)


# --- ORION projects ------------------------------------------------------------------------------------------------------------


def local_orion_project_id(project_id: uuid.UUID) -> uuid.UUID:
    """The ORION id given to a project that predates ORION ids: derived from the NOVA id, so migrating twice agrees."""
    return uuid.uuid5(PROJECT_NAMESPACE, str(project_id))


async def align_orion_project_id(
    session: AsyncSession, project: Project, reference: ProjectReference, orion_project_id: uuid.UUID
) -> bool:
    """Align a NOVA project with the ORION project its ORBIT reference reports (ADR 001 §5). Returns True when it changed.

    ORBIT is the source of truth once it reports an id: the reference records it, the project adopts it. After that the
    id is immutable (a different one is refused), an id belongs to one project only, and a project never moves between
    workspaces.
    """
    if reference.project_id != project.id or reference.system != "orbit":
        raise ValueError("the reference must be the ORBIT reference of this project")
    if reference.orion_project_id not in (None, orion_project_id):
        raise ValueError("an ORION project id never changes once ORBIT has reported it")
    holder = await session.scalar(select(Project.id).where(Project.orion_project_id == orion_project_id))
    if holder is not None and holder != project.id:
        raise ValueError("another project already holds this ORION project id")
    changed = reference.orion_project_id is None or project.orion_project_id != orion_project_id
    reference.orion_project_id = orion_project_id
    if project.orion_project_id != orion_project_id:
        project.orion_project_id = orion_project_id
        await session.flush()
    return changed


__all__ = ["as_uuid", "outbox_key", "thread_id"]
