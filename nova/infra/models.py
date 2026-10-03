"""NOVA database model (docs/ARCHITECTURE.md §8).

NOVA stores conversation/execution state, Artifacts and *references* to ORBIT context and FORGE
evaluations — never a copy of ORBIT knowledge or FORGE traces.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nova.infra.db import Base, JSONType, new_id, utcnow


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=new_id)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _pk()
    subject: Mapped[str] = mapped_column(String(255), unique=True)  # OIDC `sub`
    email: Mapped[str] = mapped_column(String(320), index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200), default="")  # job title / role ("Head of AI")
    realm_roles: Mapped[list] = mapped_column(JSONType, default=list)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_service: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    preferences: Mapped[UserPreferences | None] = relationship(back_populates="user", uselist=False, lazy="joined")


class UserPreferences(Base):
    __tablename__ = "user_preferences"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    nova_name: Mapped[str] = mapped_column(String(60), default="NOVA")
    avatar: Mapped[str] = mapped_column(String(40), default="orbit")
    tone: Mapped[str] = mapped_column(String(120), default="clear and concise")
    role: Mapped[str] = mapped_column(String(120), default="")
    teams: Mapped[list] = mapped_column(JSONType, default=list)
    preferred_methods: Mapped[list] = mapped_column(JSONType, default=list)
    artifact_format: Mapped[str] = mapped_column(String(40), default="structured")
    default_autonomy: Mapped[str] = mapped_column(String(40), default="assist")
    theme: Mapped[str] = mapped_column(String(10), default="dark")
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="preferences")


class OrbitAccount(Base):
    """Delegated ORBIT session (integration-analysis §1.7). Only the session token, encrypted."""

    __tablename__ = "orbit_accounts"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    orbit_user_id: Mapped[str] = mapped_column(String(64))
    orbit_email: Mapped[str] = mapped_column(String(320))
    orbit_name: Mapped[str] = mapped_column(String(200), default="")
    clearance: Mapped[int] = mapped_column(Integer, default=1)
    token_ciphertext: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    linked_at: Mapped[datetime] = _created()


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = _pk()
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    references: Mapped[list[ProjectReference]] = relationship(
        back_populates="project", lazy="selectin", cascade="all, delete-orphan"
    )


class ProjectMember(Base):
    __tablename__ = "project_members"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20), default="nova")  # nova | orbit (synced membership)
    created_at: Mapped[datetime] = _created()


class ProjectReference(Base):
    __tablename__ = "project_references"
    __table_args__ = (UniqueConstraint("project_id", "system", "external_id"),)
    id: Mapped[uuid.UUID] = _pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    system: Mapped[str] = mapped_column(String(20))  # orbit | forge
    external_id: Mapped[str] = mapped_column(String(200))  # ORBIT slug, FORGE agent id…
    label: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = _created()

    project: Mapped[Project] = relationship(back_populates="references")


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_updated", "user_id", "updated_at"),)
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300), default="New conversation")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)
    id: Mapped[uuid.UUID] = _pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(10))  # user | nova
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    meta: Mapped[dict] = mapped_column(JSONType, default=dict)  # composer metadata (project, refs, context mode)
    created_at: Mapped[datetime] = _created()

    blocks: Mapped[list[MessageBlock]] = relationship(
        back_populates="message", lazy="selectin", order_by="MessageBlock.position", cascade="all, delete-orphan"
    )


class MessageBlock(Base):
    __tablename__ = "message_blocks"
    __table_args__ = (UniqueConstraint("message_id", "key"),)
    id: Mapped[uuid.UUID] = _pk()
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(120))
    position: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    message: Mapped[Message] = relationship(back_populates="blocks")


class Task(Base):
    """A Work item: one NOVA execution (LangGraph thread)."""

    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_user_status", "user_id", "status"),)
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))
    message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # NOVA reply message
    objective: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    phase: Mapped[str] = mapped_column(String(30), default="idle")
    phase_label: Mapped[str] = mapped_column(String(200), default="")
    origin: Mapped[str] = mapped_column(String(20), default="interactive")
    autonomy: Mapped[str] = mapped_column(String(30), default="assist")
    trace_id: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(200))
    progress_done: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    input: Mapped[dict] = mapped_column(JSONType, default=dict)  # initial NovaState fields (no secrets)
    waiting_for: Mapped[dict | None] = mapped_column(JSONType)  # interrupt payload when waiting_user
    error: Mapped[str | None] = mapped_column(Text)
    usage: Mapped[dict] = mapped_column(JSONType, default=dict)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    steps: Mapped[list[TaskStep]] = relationship(lazy="selectin", order_by="TaskStep.position", cascade="all, delete-orphan")


class TaskStep(Base):
    __tablename__ = "task_steps"
    __table_args__ = (UniqueConstraint("task_id", "step_key"),)
    id: Mapped[uuid.UUID] = _pk()
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    step_key: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(300))
    skill_id: Mapped[str | None] = mapped_column(String(80))
    skill_version: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    detail: Mapped[str] = mapped_column(Text, default="")
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Skill(Base):
    __tablename__ = "skills"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(Text)
    current_version: Mapped[str] = mapped_column(String(20))
    system: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SkillVersion(Base):
    __tablename__ = "skill_versions"
    __table_args__ = (UniqueConstraint("skill_id", "version"),)
    id: Mapped[uuid.UUID] = _pk()
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"))
    version: Mapped[str] = mapped_column(String(20))
    content_hash: Mapped[str] = mapped_column(String(64))
    spec: Mapped[dict] = mapped_column(JSONType)
    created_at: Mapped[datetime] = _created()


class SkillExecution(Base):
    __tablename__ = "skill_executions"
    id: Mapped[uuid.UUID] = _pk()
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    step_key: Mapped[str | None] = mapped_column(String(80))
    skill_id: Mapped[str] = mapped_column(String(80), index=True)
    skill_version: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="running")
    input: Mapped[dict] = mapped_column(JSONType, default=dict)
    output: Mapped[dict | None] = mapped_column(JSONType)
    model: Mapped[str | None] = mapped_column(String(200))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class Workflow(Base):
    __tablename__ = "workflows"
    id: Mapped[uuid.UUID] = _pk()
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    objective: Mapped[str] = mapped_column(Text)
    steps: Mapped[list] = mapped_column(JSONType, default=list)  # [{id, title, skill_id, skill_version}]
    source: Mapped[str] = mapped_column(String(20), default="planned")  # planned | user
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"
    id: Mapped[uuid.UUID] = _pk()
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflows.id", ondelete="SET NULL"))
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), unique=True)
    thread_id: Mapped[str] = mapped_column(String(64))  # LangGraph checkpoint thread
    status: Mapped[str] = mapped_column(String(20), default="running")
    current_step: Mapped[str | None] = mapped_column(String(80))
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (Index("ix_artifacts_owner_updated", "owner_id", "updated_at"),)
    id: Mapped[uuid.UUID] = _pk()
    type: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | in_review | final | archived
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    classification: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ArtifactVersion(Base):
    __tablename__ = "artifact_versions"
    __table_args__ = (UniqueConstraint("artifact_id", "version"),)
    id: Mapped[uuid.UUID] = _pk()
    artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artifacts.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSONType)
    changed_sections: Mapped[list] = mapped_column(JSONType, default=list)
    author_type: Mapped[str] = mapped_column(String(10))  # user | nova
    author_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    skill_execution_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    summary: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(20), default="current")  # current | superseded | proposed | rejected
    created_at: Mapped[datetime] = _created()


class ArtifactComment(Base):
    __tablename__ = "artifact_comments"
    id: Mapped[uuid.UUID] = _pk()
    artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artifacts.id", ondelete="CASCADE"), index=True)
    section_key: Mapped[str] = mapped_column(String(80))
    item_id: Mapped[str | None] = mapped_column(String(80))
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    body: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()


class ContextRetrievalReference(Base):
    """What ORBIT served to this user for one execution (titles/ids/short excerpts for citations)."""

    __tablename__ = "context_retrieval_references"
    id: Mapped[uuid.UUID] = _pk()
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    system: Mapped[str] = mapped_column(String(20), default="orbit")
    project_slug: Mapped[str | None] = mapped_column(String(120))
    retrieval_id: Mapped[str | None] = mapped_column(String(64))  # ORBIT request_id
    trace_id: Mapped[str | None] = mapped_column(String(64))
    query: Mapped[str] = mapped_column(Text, default="")
    items: Mapped[list] = mapped_column(JSONType, default=list)
    warnings: Mapped[list] = mapped_column(JSONType, default=list)
    max_classification: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created()


class ToolExecution(Base):
    __tablename__ = "tool_executions"
    id: Mapped[uuid.UUID] = _pk()
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    skill_execution_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    tool: Mapped[str] = mapped_column(String(80))
    input: Mapped[dict] = mapped_column(JSONType, default=dict)
    output: Mapped[dict | None] = mapped_column(JSONType)
    status: Mapped[str] = mapped_column(String(20))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    duration_ms: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class ExecutionEvent(Base):
    __tablename__ = "execution_events"
    __table_args__ = (UniqueConstraint("task_id", "seq"),)
    id: Mapped[uuid.UUID] = _pk()
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = _created()


class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    rating: Mapped[str] = mapped_column(String(20))
    comment: Mapped[str | None] = mapped_column(Text)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    skill_id: Mapped[str | None] = mapped_column(String(80))
    skill_version: Mapped[str | None] = mapped_column(String(20))
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    trace_id: Mapped[str | None] = mapped_column(String(64))
    forwarded: Mapped[dict] = mapped_column(JSONType, default=dict)  # {orbit: bool, forge: bool}
    created_at: Mapped[datetime] = _created()


class IntegrationReference(Base):
    """Link between a NOVA object and an object in ORBIT/FORGE (e.g. task → FORGE run)."""

    __tablename__ = "integration_references"
    __table_args__ = (UniqueConstraint("system", "kind", "nova_type", "nova_id"),)
    id: Mapped[uuid.UUID] = _pk()
    system: Mapped[str] = mapped_column(String(20))  # orbit | forge
    kind: Mapped[str] = mapped_column(String(40))  # evaluation | agent_version | memory | document
    nova_type: Mapped[str] = mapped_column(String(40))  # task | artifact | release
    nova_id: Mapped[str] = mapped_column(String(64))
    external_id: Mapped[str] = mapped_column(String(200))
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_created", "created_at"),)
    id: Mapped[uuid.UUID] = _pk()
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    action: Mapped[str] = mapped_column(String(80))
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(64))
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    summary: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = _created()
