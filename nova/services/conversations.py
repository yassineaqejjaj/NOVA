"""Conversations: a user intent becomes a NOVA reply message + a Work item executed in the background."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.domain.enums import AutonomyMode, ExecutionOrigin, TaskStatus
from nova.domain.permissions import Principal
from nova.infra.models import Conversation, LearnedSkill, Message, Project, Task, UserPreferences
from nova.services.access import AccessDenied, project_role
from nova.services.teach import expand as expand_learned
from nova.services.users import get_user, preferences_dict

SLASH = re.compile(r"(?<!\S)/([a-z][a-z0-9-]+)")


class ComposerInput(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    project_id: str | None = None
    context_mode: Literal["auto", "explicit", "none"] = "auto"
    pinned_context_ref_ids: list[str] = Field(default_factory=list, max_length=20)
    excluded_context_refs: list[str] = Field(default_factory=list, max_length=50)
    artifact_refs: list[str] = Field(default_factory=list, max_length=10)
    skill_refs: list[str] = Field(default_factory=list, max_length=8)
    active_artifact_id: str | None = None
    autonomy: AutonomyMode | None = None
    attachments: list[dict[str, str]] = Field(default_factory=list, max_length=5)  # {name, text} (extracted client-side)
    scheduled_for: datetime | None = None
    edit_target: dict[str, Any] | None = None  # {"artifact_id", "sections"} (section regeneration)


def extract_skill_refs(text: str, known: set[str]) -> list[str]:
    return [m for m in dict.fromkeys(SLASH.findall(text)) if m in known]


async def create_conversation(
    session: AsyncSession, principal: Principal, *, project_id: str | None, title: str | None
) -> Conversation:
    pid = uuid.UUID(project_id) if project_id else None
    if pid and await project_role(session, pid, uuid.UUID(principal.user_id)) is None and not principal.is_admin:
        raise AccessDenied
    conversation = Conversation(user_id=uuid.UUID(principal.user_id), project_id=pid, title=(title or "New conversation")[:300])
    session.add(conversation)
    await session.flush()
    return conversation


async def _history(session: AsyncSession, conversation_id: uuid.UUID, limit: int = 6) -> list[dict[str, str]]:
    messages = (
        await session.scalars(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.desc()).limit(limit)
        )
    ).all()
    history = []
    for m in reversed(messages):
        if m.role == "user":
            history.append({"role": "user", "text": str(m.meta.get("text", ""))})
        else:
            texts = [b.payload.get("markdown", "") for b in m.blocks if b.type == "text"]
            if texts:
                history.append({"role": "nova", "text": " ".join(texts)[:800]})
    return history


async def submit(
    session: AsyncSession, principal: Principal, conversation: Conversation, data: ComposerInput, known_skills: set[str]
) -> tuple[Message, Message, Task]:
    """Persist the user message, the (empty) NOVA reply and the task. The caller dispatches the task."""
    user = await get_user(session, principal.user_id)
    assert user is not None
    project_id = uuid.UUID(data.project_id) if data.project_id else conversation.project_id
    project_slug = None
    if project_id:
        if await project_role(session, project_id, user.id) is None and not principal.is_admin:
            raise AccessDenied
        project = await session.get(Project, project_id)
        orbit_ref = next((r for r in project.references if r.system == "orbit"), None) if project else None
        project_slug = orbit_ref.external_id if orbit_ref else None

    prefs = await session.get(UserPreferences, user.id)
    preferences = preferences_dict(prefs, user)
    history = await _history(session, conversation.id)
    intent = data.text
    learned_refs: list[str] = []
    first = data.text.strip().split(maxsplit=1)
    if first and first[0].startswith("/") and first[0][1:] not in known_skills:
        learned = await session.scalar(
            select(LearnedSkill).where(LearnedSkill.user_id == user.id, LearnedSkill.slug == first[0][1:].lower())
        )
        if learned is not None:  # "/my-workflow …": a Skill NOVA learned from this user (Teach NOVA)
            intent, learned_refs = expand_learned(learned, first[1] if len(first) > 1 else "")
            learned.uses += 1
    skill_refs = list(
        dict.fromkeys([s for s in data.skill_refs if s in known_skills] + learned_refs + extract_skill_refs(intent, known_skills))
    )
    autonomy = data.autonomy or AutonomyMode(preferences.get("default_autonomy") or "assist")

    user_message = Message(
        conversation_id=conversation.id,
        role="user",
        meta={
            "text": data.text,
            "project_id": str(project_id) if project_id else None,
            "context_mode": data.context_mode,
            "artifact_refs": data.artifact_refs,
            "skill_refs": skill_refs,
            "attachments": [a.get("name") for a in data.attachments],
        },
    )
    session.add(user_message)
    await session.flush()
    reply = Message(conversation_id=conversation.id, role="nova", meta={})
    session.add(reply)
    await session.flush()

    task_input: dict[str, Any] = {
        "conversation_id": str(conversation.id),
        "message_id": str(reply.id),
        "project_id": str(project_id) if project_id else None,
        "project_slug": project_slug,
        "origin": ExecutionOrigin.interactive.value,
        "autonomy": autonomy.value,
        "intent": intent,
        "history": history,
        "active_artifact_id": data.active_artifact_id,
        "artifact_refs": data.artifact_refs,
        "skill_refs": skill_refs,
        "edit_target": data.edit_target,
        "context_mode": data.context_mode,
        "pinned_context_ref_ids": data.pinned_context_ref_ids,
        "excluded_context_refs": data.excluded_context_refs,
        "attachments": data.attachments,
        "preferences": preferences,
    }
    task = Task(
        user_id=user.id,
        project_id=project_id,
        conversation_id=conversation.id,
        message_id=reply.id,
        objective=data.text[:2000],
        autonomy=autonomy.value,
        input=task_input,
        status=TaskStatus.scheduled.value if data.scheduled_for else TaskStatus.queued.value,
        scheduled_for=data.scheduled_for,
    )
    session.add(task)
    await session.flush()
    reply.task_id = task.id
    if conversation.title == "New conversation":
        conversation.title = data.text.strip().splitlines()[0][:120]
    if project_id and conversation.project_id is None:
        conversation.project_id = project_id
    return user_message, reply, task
