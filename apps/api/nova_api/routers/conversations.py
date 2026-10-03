"""Conversations (block-based) and intents."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.domain.permissions import Principal
from nova.infra.db import get_session
from nova.infra.models import Conversation, Message, Task
from nova.services.access import AccessDenied
from nova.services.conversations import ComposerInput, create_conversation, submit
from nova.services.dispatch import dispatch
from nova.skills.registry import get_skill_registry
from nova_api.auth import CurrentPrincipal

router = APIRouter(prefix="/conversations", tags=["conversations"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


class ConversationIn(BaseModel):
    project_id: str | None = None
    title: str | None = Field(default=None, max_length=300)


class ConversationPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    archived: bool | None = None


def task_view(task: Task | None) -> dict[str, Any] | None:
    if task is None:
        return None
    return {
        "id": str(task.id),
        "status": task.status,
        "phase": task.phase,
        "phase_label": task.phase_label,
        "progress_done": task.progress_done,
        "progress_total": task.progress_total,
        "waiting_for": task.waiting_for,
        "trace_id": task.trace_id,
    }


def message_view(message: Message, task: Task | None) -> dict[str, Any]:
    return {
        "id": str(message.id),
        "role": message.role,
        "created_at": message.created_at.isoformat(),
        "meta": message.meta,
        "blocks": [{"key": b.key, "type": b.type, "position": b.position, "data": b.payload} for b in message.blocks],
        "task": task_view(task),
    }


async def _owned(session: AsyncSession, principal: Principal, conversation_id: str) -> Conversation:
    try:
        conversation = await session.get(Conversation, uuid.UUID(conversation_id))
    except ValueError as exc:
        raise AccessDenied from exc
    if conversation is None or str(conversation.user_id) != principal.user_id:
        raise AccessDenied
    return conversation


def conversation_view(c: Conversation) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "title": c.title,
        "project_id": str(c.project_id) if c.project_id else None,
        "archived": c.archived,
        "updated_at": c.updated_at.isoformat(),
    }


@router.get("")
async def list_conversations(
    principal: CurrentPrincipal, session: SessionDep, project_id: str | None = None, limit: int = Query(30, le=100)
) -> list[dict[str, Any]]:
    query = select(Conversation).where(Conversation.user_id == uuid.UUID(principal.user_id), Conversation.archived.is_(False))
    if project_id:
        query = query.where(Conversation.project_id == uuid.UUID(project_id))
    rows = (await session.scalars(query.order_by(Conversation.updated_at.desc()).limit(limit))).all()
    return [conversation_view(c) for c in rows]


@router.post("", status_code=201)
async def new_conversation(body: ConversationIn, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    conversation = await create_conversation(session, principal, project_id=body.project_id, title=body.title)
    await session.commit()
    return conversation_view(conversation)


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    conversation = await _owned(session, principal, conversation_id)
    messages = (
        await session.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at))
    ).all()
    task_ids = [m.task_id for m in messages if m.task_id]
    tasks = {t.id: t for t in (await session.scalars(select(Task).where(Task.id.in_(task_ids)))).all()} if task_ids else {}
    return {
        **conversation_view(conversation),
        "messages": [message_view(m, tasks.get(m.task_id) if m.task_id else None) for m in messages],
    }


@router.patch("/{conversation_id}")
async def update_conversation(
    conversation_id: str, body: ConversationPatch, principal: CurrentPrincipal, session: SessionDep
) -> dict[str, Any]:
    conversation = await _owned(session, principal, conversation_id)
    if body.title:
        conversation.title = body.title
    if body.archived is not None:
        conversation.archived = body.archived
    await session.commit()
    return conversation_view(conversation)


@router.post("/{conversation_id}/messages", status_code=202)
async def send_message(
    conversation_id: str, body: ComposerInput, principal: CurrentPrincipal, session: SessionDep
) -> dict[str, Any]:
    """Express an intent. Returns immediately; follow ``/executions/{task_id}/events`` for live progress."""
    conversation = await _owned(session, principal, conversation_id)
    user_message, reply, task = await submit(session, principal, conversation, body, {s.id for s in get_skill_registry().all()})
    await session.commit()
    if task.status == "queued":
        await dispatch(str(task.id), "start")
    await session.refresh(user_message, ["blocks"])
    await session.refresh(reply, ["blocks"])
    await session.refresh(task)
    return {
        "user_message": message_view(user_message, None),
        "message": message_view(reply, task),
        "task": task_view(task),
        "conversation": conversation_view(conversation),
    }
