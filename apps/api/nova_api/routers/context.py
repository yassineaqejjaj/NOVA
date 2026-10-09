"""ORBIT Context surface — shows what ORBIT provides; never a memory management screen."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.config import get_settings
from nova.domain.context import ContextError, ContextQuery, SnapshotRef
from nova.domain.enums import CLASSIFICATION_LABELS
from nova.infra.db import get_session
from nova.infra.models import ContextRetrievalReference, Project, ProjectReference
from nova.services import orbit_snapshots, providers
from nova.services.access import AccessDenied, project_role
from nova.services.execution_store import SqlExecutionStore
from nova_api.auth import CurrentPrincipal

router = APIRouter(prefix="/context", tags=["context"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


class RetrieveIn(BaseModel):
    project_id: str
    query: str = Field(min_length=2, max_length=4000)
    token_budget: int = Field(default=3000, ge=500, le=8000)


async def _orbit_slug(session: AsyncSession, user_id: str, project_id: str) -> str:
    pid = uuid.UUID(project_id)
    if await project_role(session, pid, uuid.UUID(user_id)) is None:
        raise AccessDenied
    slug = await session.scalar(
        select(ProjectReference.external_id).where(ProjectReference.project_id == pid, ProjectReference.system == "orbit")
    )
    if not slug:
        raise ContextError("not_found", "This project is not linked to ORBIT.")
    return slug


def _item_view(item: dict[str, Any]) -> dict[str, Any]:
    return {**item, "classification_label": CLASSIFICATION_LABELS.get(item.get("classification", 1))}


@router.get("")
async def overview(principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    """Your profile in ORBIT, linked projects and recent context NOVA used for you."""
    identity = await providers.context().identity(principal.user_id)
    projects = (
        await session.execute(
            select(Project.id, Project.name, ProjectReference.external_id, ProjectReference.url)
            .join(ProjectReference, (ProjectReference.project_id == Project.id) & (ProjectReference.system == "orbit"))
            .where(Project.id.in_(select_member_projects(principal.user_id)))
        )
    ).all()
    refs = (
        await session.scalars(
            select(ContextRetrievalReference)
            .where(ContextRetrievalReference.user_id == uuid.UUID(principal.user_id))
            .order_by(ContextRetrievalReference.created_at.desc())
            .limit(10)
        )
    ).all()
    return {
        "orbit_url": get_settings().orbit_public_url,
        "identity": identity.model_dump(mode="json"),
        "projects": [{"id": str(pid), "name": name, "orbit_slug": slug, "orbit_url": url} for pid, name, slug, url in projects],
        "recent": [
            {
                "id": str(r.id),
                "task_id": str(r.task_id) if r.task_id else None,
                "project_slug": r.project_slug,
                "query": r.query[:200],
                "count": len(r.items),
                "max_classification": r.max_classification,
                "snapshot": {"name": r.snapshot_name, "version": r.snapshot_version} if r.snapshot_name else None,
                "created_at": r.created_at.isoformat(),
                "items": [_item_view(i) for i in r.items[:6]],
            }
            for r in refs
        ],
    }


def select_member_projects(user_id: str):
    from nova.infra.models import ProjectMember

    return select(ProjectMember.project_id).where(ProjectMember.user_id == uuid.UUID(user_id))


@router.get("/projects/{project_id}")
async def project_context(project_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    """Recent decisions, documents and changes ORBIT exposes to this user for the project."""
    slug = await _orbit_slug(session, principal.user_id, project_id)
    changes = await providers.context().recent_changes(principal.user_id, slug, None)
    decisions = [c for c in changes if c.type.startswith("memory.") and (c.data or {}).get("kind", "decision") == "decision"]
    documents = [c for c in changes if c.type.startswith("document.")]
    return {
        "orbit_slug": slug,
        "decisions": [c.model_dump(mode="json") for c in decisions[:10]],
        "documents": [c.model_dump(mode="json") for c in documents[:10]],
        "changes": [c.model_dump(mode="json") for c in changes[:20]],
    }


class SnapshotRefIn(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=200)
    version: int | None = Field(default=None, ge=1)  # None: follow the latest version


def _reference_view(ref: SnapshotRef | None) -> dict[str, Any] | None:
    return ref.model_dump(mode="json") if ref else None


@router.get("/snapshots")
async def list_snapshots(principal: CurrentPrincipal, session: SessionDep, project_id: str) -> dict[str, Any]:
    """Snapshots ORBIT lists for the project (with the user's own rights) + the reference snapshot NOVA applies."""
    slug = await _orbit_slug(session, principal.user_id, project_id)
    found = await providers.context().list_snapshots(principal.user_id, slug)
    return {
        "orbit_slug": slug,
        "snapshots": [s.model_dump(mode="json") for s in found],
        "reference": _reference_view(await orbit_snapshots.get_reference(principal.user_id, slug)),
    }


@router.get("/snapshots/{name}")
async def get_snapshot(
    name: str, principal: CurrentPrincipal, session: SessionDep, project_id: str, version: int | None = Query(default=None, ge=1)
) -> dict[str, Any]:
    """One snapshot version read live from ORBIT (nothing is stored in NOVA); ``version`` omitted = latest."""
    slug = await _orbit_slug(session, principal.user_id, project_id)
    snap = await providers.context().get_snapshot(principal.user_id, slug, name, version)
    return {"orbit_slug": slug, "snapshot": snap.model_dump(mode="json")}


@router.put("/snapshots/reference")
async def set_snapshot_reference(body: SnapshotRefIn, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    """ "Use for agents": the snapshot becomes ``base_snapshot`` of this user's retrievals on the project."""
    slug = await _orbit_slug(session, principal.user_id, body.project_id)
    ref = SnapshotRef(name=body.name, version=body.version)
    await providers.context().get_snapshot(
        principal.user_id, slug, ref.name, ref.version
    )  # must exist and be readable by the user
    await orbit_snapshots.set_reference(principal.user_id, slug, ref)
    return {"orbit_slug": slug, "reference": _reference_view(ref)}


@router.delete("/snapshots/reference")
async def clear_snapshot_reference(principal: CurrentPrincipal, session: SessionDep, project_id: str) -> dict[str, Any]:
    slug = await _orbit_slug(session, principal.user_id, project_id)
    await orbit_snapshots.clear_reference(principal.user_id, slug)
    return {"orbit_slug": slug, "reference": None}


@router.get("/search")
async def search(
    principal: CurrentPrincipal, session: SessionDep, project_id: str, q: str = Query(min_length=2, max_length=300)
) -> list[dict[str, Any]]:
    slug = await _orbit_slug(session, principal.user_id, project_id)
    return [h.model_dump(mode="json") for h in await providers.context().search(principal.user_id, slug, q, 12)]


@router.post("/retrieve")
async def retrieve(body: RetrieveIn, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    """Explicit context ("Add context"): governed retrieval recorded so the composer can pin it."""
    slug = await _orbit_slug(session, principal.user_id, body.project_id)
    bundle = await providers.context().retrieve(
        ContextQuery(user_id=principal.user_id, project_slug=slug, task=body.query, token_budget=body.token_budget)
    )
    reference_id = await SqlExecutionStore(principal).record_context(
        task_id="", user_id=principal.user_id, conversation_id=None, query=body.query, bundle=bundle
    )
    return {
        "reference_id": reference_id,
        "retrieval_id": bundle.retrieval_id,
        "warnings": bundle.warnings,
        "items": [_item_view(i.model_dump(mode="json")) for i in bundle.items],
    }


@router.get("/references/{reference_id}")
async def reference(reference_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    row = await session.get(ContextRetrievalReference, uuid.UUID(reference_id))
    if row is None or str(row.user_id) != principal.user_id:
        raise AccessDenied
    return {
        "id": str(row.id),
        "project_slug": row.project_slug,
        "retrieval_id": row.retrieval_id,
        "query": row.query,
        "warnings": row.warnings,
        "items": [_item_view(i) for i in row.items],
        "created_at": row.created_at.isoformat(),
    }
