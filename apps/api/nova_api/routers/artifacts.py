"""Artifacts: CRUD, autosave, versions, compare, comments, export, provenance, section regeneration, approvals."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.artifacts.registry import get_artifact_registry
from nova.domain.enums import ProjectRole
from nova.infra.db import get_session
from nova.infra.models import ArtifactVersion, Conversation, Task
from nova.services import artifacts as service
from nova.services.access import require_artifact
from nova.services.conversations import ComposerInput, create_conversation, submit
from nova.services.dispatch import dispatch
from nova.services.execution_store import SqlExecutionStore
from nova.skills.registry import get_skill_registry
from nova_api.auth import CurrentPrincipal
from nova_api.errors import ApiError

router = APIRouter(prefix="/artifacts", tags=["artifacts"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


class ArtifactIn(BaseModel):
    type: str
    title: str = Field(min_length=1, max_length=300)
    project_id: str | None = None


class ArtifactPatch(BaseModel):
    base_version: int
    sections: dict[str, Any] | None = None
    title: str | None = Field(default=None, max_length=300)
    status: Literal["draft", "in_review", "final", "archived"] | None = None


class CommentIn(BaseModel):
    section_key: str
    item_id: str | None = None
    body: str = Field(min_length=1, max_length=4000)


class RegenerateIn(BaseModel):
    instruction: str = Field(default="", max_length=2000)


@router.get("")
async def list_artifacts(
    principal: CurrentPrincipal,
    session: SessionDep,
    project_id: str | None = None,
    type: str | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    return await service.list_artifacts(session, principal, project_id=project_id, type_=type, q=q)


@router.get("/types")
async def artifact_types(principal: CurrentPrincipal) -> list[dict[str, Any]]:
    return [t.model_dump(mode="json") for t in get_artifact_registry().types.values()]


@router.get("/item-kinds")
async def item_kinds(principal: CurrentPrincipal) -> dict[str, Any]:
    """JSON Schemas of item attributes (stories, requirements, metrics…), used by the editor to build forms."""
    return get_artifact_registry().item_schemas


@router.post("", status_code=201)
async def create(body: ArtifactIn, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    if body.type not in get_artifact_registry().types:
        raise ApiError(422, "validation_error", "Unknown artifact type.")
    result = await service.create_artifact(session, principal, type_=body.type, title=body.title, project_id=body.project_id)
    await session.commit()
    return result


@router.get("/{artifact_id}")
async def get(artifact_id: str, principal: CurrentPrincipal, session: SessionDep, version: int | None = None) -> dict[str, Any]:
    return await service.get_artifact(session, principal, artifact_id, version)


@router.patch("/{artifact_id}")
async def update(artifact_id: str, body: ArtifactPatch, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    try:
        result = await service.save_user_edit(
            session,
            principal,
            artifact_id,
            base_version=body.base_version,
            sections=body.sections,
            title=body.title,
            status=body.status,
        )
    except service.VersionConflict as exc:
        raise ApiError(
            409,
            "version_conflict",
            "This Artifact changed since you opened it (NOVA or a teammate saved a new version).",
            [{"label": "Reload", "action": "reload"}],
        ) from exc
    except ValueError as exc:
        raise ApiError(422, "validation_error", str(exc)) from exc
    await session.commit()
    return result


@router.get("/{artifact_id}/versions")
async def versions(artifact_id: str, principal: CurrentPrincipal, session: SessionDep) -> list[dict[str, Any]]:
    return await service.list_versions(session, principal, artifact_id)


@router.get("/{artifact_id}/compare")
async def compare(
    artifact_id: str,
    principal: CurrentPrincipal,
    session: SessionDep,
    v_from: int = Query(alias="from"),
    v_to: int = Query(alias="to"),
) -> dict[str, Any]:
    return await service.compare(session, principal, artifact_id, v_from, v_to)


@router.get("/{artifact_id}/comments")
async def comments(artifact_id: str, principal: CurrentPrincipal, session: SessionDep) -> list[dict[str, Any]]:
    return await service.comments(session, principal, artifact_id)


@router.post("/{artifact_id}/comments", status_code=201)
async def add_comment(artifact_id: str, body: CommentIn, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    result = await service.add_comment(
        session, principal, artifact_id, section_key=body.section_key, item_id=body.item_id, body=body.body
    )
    await session.commit()
    return result


@router.post("/{artifact_id}/comments/{comment_id}/resolve", status_code=204)
async def resolve_comment(artifact_id: str, comment_id: str, principal: CurrentPrincipal, session: SessionDep) -> None:
    await service.resolve_comment(session, principal, artifact_id, comment_id)
    await session.commit()


@router.get("/{artifact_id}/export")
async def export(
    artifact_id: str, principal: CurrentPrincipal, session: SessionDep, format: Literal["md", "json"] = "md"
) -> Response:
    body, media_type, filename = await service.export(session, principal, artifact_id, format)
    return Response(body, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/{artifact_id}/provenance")
async def provenance(
    artifact_id: str, principal: CurrentPrincipal, session: SessionDep, section: str | None = None, item: str | None = None
) -> dict[str, Any]:
    return await service.provenance(session, principal, artifact_id, section_key=section, item_id=item)


@router.post("/{artifact_id}/sections/{section_key}/regenerate", status_code=202)
async def regenerate(
    artifact_id: str, section_key: str, body: RegenerateIn, principal: CurrentPrincipal, session: SessionDep
) -> dict[str, Any]:
    """Section-level AI update: runs the Artifact-edit Skill on this section only, in the Artifact's conversation."""
    artifact, _ = await require_artifact(session, artifact_id, principal, ProjectRole.editor)
    definition = get_artifact_registry().get(artifact.type).section(section_key)
    if definition is None:
        raise ApiError(404, "not_found", "Unknown section.")
    conversation = await session.get(Conversation, artifact.conversation_id) if artifact.conversation_id else None
    if conversation is None or str(conversation.user_id) != principal.user_id:
        conversation = await create_conversation(
            session, principal, project_id=str(artifact.project_id) if artifact.project_id else None, title=artifact.title
        )
    text = body.instruction.strip() or f'Regenerate the section "{definition.title}".'
    _, reply, task = await submit(
        session,
        principal,
        conversation,
        ComposerInput(
            text=text,
            project_id=str(artifact.project_id) if artifact.project_id else None,
            active_artifact_id=artifact_id,
            edit_target={"artifact_id": artifact_id, "sections": [section_key]},
        ),
        {s.id for s in get_skill_registry().all()},
    )
    await session.commit()
    await dispatch(str(task.id), "start")
    return {"task_id": str(task.id), "conversation_id": str(conversation.id), "message_id": str(reply.id)}


@router.post("/{artifact_id}/versions/{version}/approve")
async def approve(artifact_id: str, version: int, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    """Approve a proposed version outside the conversation (resumes the waiting execution if any)."""
    artifact, _ = await require_artifact(session, artifact_id, principal, ProjectRole.editor)
    row = await session.scalar(
        select(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact.id, ArtifactVersion.version == version)
    )
    if row is None or row.state != "proposed":
        raise ApiError(409, "not_proposed", "This version is not waiting for approval.")
    task = await session.get(Task, row.task_id) if row.task_id else None
    if task and task.status == "waiting_user" and (task.waiting_for or {}).get("kind") == "approval":
        task.status = "queued"
        await session.commit()
        await dispatch(str(task.id), "resume", {"action": "approve"})
    else:
        await session.commit()
        await SqlExecutionStore(principal).promote_proposed_version(artifact_id, version, principal.user_id)
    return {"status": "approved"}
