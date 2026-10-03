"""Audit log (logins, ORBIT links, executions, approvals, external writes, Artifact changes)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from nova.infra.models import AuditEvent
from nova.infra.redaction import redact_obj


async def audit(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | str | None,
    action: str,
    target_type: str,
    target_id: str | None = None,
    summary: str = "",
    project_id: uuid.UUID | str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            actor_id=uuid.UUID(str(actor_id)) if actor_id else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            project_id=uuid.UUID(str(project_id)) if project_id else None,
            summary=summary[:500],
            details=redact_obj(details or {}),
        )
    )
    await session.flush()
