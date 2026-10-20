"""Nova Quality surface: what FORGE evaluated about the user's work, and the health of the link."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.config import get_settings
from nova.infra.db import get_session
from nova.infra.models import IntegrationReference, Task
from nova.integrations import link_health
from nova_api.auth import CurrentPrincipal

router = APIRouter(prefix="/quality", tags=["quality"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
RECENT = 20


@router.get("")
async def overview(principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    settings = get_settings()
    tasks = (
        await session.execute(
            select(Task.id, Task.objective)
            .where(Task.user_id == uuid.UUID(principal.user_id))
            .order_by(Task.created_at.desc())
            .limit(200)
        )
    ).all()
    objectives = {str(task_id): objective for task_id, objective in tasks}
    refs = (
        await session.scalars(
            select(IntegrationReference)
            .where(
                IntegrationReference.system == "forge",
                IntegrationReference.kind == "evaluation",
                IntegrationReference.nova_type == "task",
                IntegrationReference.nova_id.in_(list(objectives)),
            )
            .order_by(IntegrationReference.updated_at.desc())
        )
    ).all()
    evaluations = [
        {
            "task_id": ref.nova_id,
            "objective": objectives[ref.nova_id],
            "score": (ref.data or {}).get("composite_score"),
            "passed": (ref.data or {}).get("passed"),
            "status": (ref.data or {}).get("status"),
            "url": (ref.data or {}).get("url"),
            "at": ref.updated_at.isoformat(),
        }
        for ref in refs
    ]
    scored = [e["score"] for e in evaluations if isinstance(e["score"], int | float)]
    judged = [e for e in evaluations if e["passed"] is not None]
    state = await link_health.forge_state()
    return {
        "forge_url": settings.forge_public_url,
        "monitoring": bool(settings.forge_api_key),
        "capture_policy": settings.forge_capture_policy,
        "link": state,
        "summary": {
            "evaluated": len(evaluations),
            "average_score": round(sum(scored) / len(scored), 1) if scored else None,
            "pass_rate": round(100 * sum(1 for e in judged if e["passed"]) / len(judged)) if judged else None,
        },
        "recent": evaluations[:RECENT],
    }
