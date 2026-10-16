"""Forgetting (administrators): erase the context NOVA kept, by ORBIT source, project or user (NOV-98)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.infra.db import aware, get_session
from nova.infra.models import ForgetRequest
from nova.services import forget
from nova_api.auth import CurrentPrincipal
from nova_api.errors import ApiError

router = APIRouter(prefix="/admin/forget", tags=["forget"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
LISTED = 50


class ForgetIn(BaseModel):
    scope: Literal["source", "project", "user"]
    document_id: str | None = Field(default=None, max_length=80)
    memory_item_id: str | None = Field(default=None, max_length=80)
    project_slug: str | None = Field(default=None, max_length=120)
    user_id: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def _target(self) -> ForgetIn:
        needed = {"source": self.document_id or self.memory_item_id, "project": self.project_slug, "user": self.user_id}
        if not needed[self.scope]:
            raise ValueError(f"scope '{self.scope}' needs its target")
        return self


def _admin(principal: Any) -> None:
    if not principal.is_admin:
        raise ApiError(403, "forbidden", "Only an administrator can forget data.")


@router.post("")
async def ask(body: ForgetIn, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    _admin(principal)
    if body.scope == "source":
        effects = await forget.forget_source(
            session,
            document_id=body.document_id,
            memory_item_id=body.memory_item_id,
            project_slug=body.project_slug,
            actor_id=principal.user_id,
        )
    elif body.scope == "project":
        effects = await forget.forget_project(session, project_slug=body.project_slug or "", actor_id=principal.user_id)
    else:
        effects = await forget.forget_user(session, user_id=body.user_id or "", actor_id=principal.user_id)
    await session.commit()
    return {"status": "partial" if effects.get("errors") else "completed", "effects": effects}


@router.get("")
async def requests(principal: CurrentPrincipal, session: SessionDep) -> list[dict[str, Any]]:
    _admin(principal)
    rows = await session.scalars(select(ForgetRequest).order_by(ForgetRequest.created_at.desc()).limit(LISTED))
    return [
        {
            "id": str(r.id),
            "scope": r.scope,
            "target": r.target,
            "origin": r.origin,
            "status": r.status,
            "effects": r.effects,
            "error": r.error,
            "created_at": aware(r.created_at).isoformat(),
        }
        for r in rows
    ]
