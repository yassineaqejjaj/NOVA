"""The ORBIT snapshot a user chose as the reference of a project. Stores the reference only, never the content."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from nova.domain.context import SnapshotRef
from nova.infra.db import session_scope
from nova.infra.models import OrbitSnapshotReference


async def _row(session, user_id: str, project_slug: str) -> OrbitSnapshotReference | None:
    return await session.scalar(
        select(OrbitSnapshotReference).where(
            OrbitSnapshotReference.user_id == uuid.UUID(user_id), OrbitSnapshotReference.project_slug == project_slug
        )
    )


async def get_reference(user_id: str, project_slug: str) -> SnapshotRef | None:
    """The enabled reference snapshot (``version=None`` follows the latest), or ``None``."""
    async with session_scope() as session:
        row = await _row(session, user_id, project_slug)
        if row is None or not row.enabled:
            return None
        return SnapshotRef(name=row.snapshot_name, version=row.pinned_version)


async def list_references(user_id: str, project_slugs: list[str]) -> dict[str, tuple[SnapshotRef, datetime]]:
    async with session_scope() as session:
        rows = (
            await session.scalars(
                select(OrbitSnapshotReference).where(
                    OrbitSnapshotReference.user_id == uuid.UUID(user_id),
                    OrbitSnapshotReference.project_slug.in_(project_slugs),
                    OrbitSnapshotReference.enabled.is_(True),
                )
            )
        ).all()
        return {r.project_slug: (SnapshotRef(name=r.snapshot_name, version=r.pinned_version), r.updated_at) for r in rows}


async def set_reference(user_id: str, project_slug: str, ref: SnapshotRef) -> None:
    async with session_scope() as session:
        row = await _row(session, user_id, project_slug)
        if row is None:
            row = OrbitSnapshotReference(user_id=uuid.UUID(user_id), project_slug=project_slug, snapshot_name=ref.name)
            session.add(row)
        row.snapshot_name, row.pinned_version, row.enabled = ref.name, ref.version, True


async def clear_reference(user_id: str, project_slug: str) -> None:
    async with session_scope() as session:
        row = await _row(session, user_id, project_slug)
        if row is not None:
            await session.delete(row)
