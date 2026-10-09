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
    language: Mapped[str | None] = mapped_column(String(5))  # "en" | "fr"; None = follow the browser
    orb_color: Mapped[str] = mapped_column(String(20), default="coral", server_default="coral")
    profile: Mapped[str] = mapped_column(String(20), default="product", server_default="product")  # AgentProfile
    # Always / Ask / Never per action ({"artifacts.update": "ask", …}); unset actions follow the autonomy level
    action_permissions: Mapped[dict] = mapped_column(JSONType, default=dict, server_default="{}")
    today_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # "since your last visit"
    teaching_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # Teach NOVA session in progress
    dismissed_recommendations: Mapped[list] = mapped_column(JSONType, default=list, server_default="[]")
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


class OrbitSnapshotReference(Base):
    """The ORBIT snapshot a user wants NOVA's agents to use for a project. Reference only: never the content."""

    __tablename__ = "orbit_snapshot_references"
    __table_args__ = (UniqueConstraint("user_id", "project_slug"),)
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_slug: Mapped[str] = mapped_column(String(120))
    snapshot_name: Mapped[str] = mapped_column(String(200))
    pinned_version: Mapped[int | None] = mapped_column(Integer)  # None = follow the latest version
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class FigmaAccount(Base):
    """Figma link of a user: OAuth tokens (MCP) or a personal access token (REST, read-only). Encrypted."""

    __tablename__ = "figma_accounts"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    mode: Mapped[str] = mapped_column(String(10))  # oauth | token
    figma_user_id: Mapped[str] = mapped_column(String(64), default="")
    handle: Mapped[str] = mapped_column(String(200), default="")
    token_ciphertext: Mapped[str | None] = mapped_column(Text)
    refresh_ciphertext: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scope: Mapped[str] = mapped_column(String(500), default="")
    linked_at: Mapped[datetime] = _created()


class UserLLMConfig(Base):
    """The user's own LLM (bring your own key). The key is stored encrypted and never returned by the API."""

    __tablename__ = "user_llm_configs"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(30))  # anthropic | openai | google | mistral | openrouter | custom
    model: Mapped[str] = mapped_column(String(120))
    base_url: Mapped[str] = mapped_column(String(500), default="")  # custom endpoints only
    key_ciphertext: Mapped[str] = mapped_column(Text)
    key_hint: Mapped[str] = mapped_column(String(12), default="")  # last characters, for display
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class GithubAccount(Base):
    """GitHub link of a user (personal access token, encrypted)."""

    __tablename__ = "github_accounts"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    login: Mapped[str] = mapped_column(String(100), default="")
    token_ciphertext: Mapped[str] = mapped_column(Text)
    scopes: Mapped[str] = mapped_column(String(500), default="")
    linked_at: Mapped[datetime] = _created()


class SdlcRun(Base):
    """One autonomous software-delivery run: intent → spec → design → code → tests → PR → review → CI → merge → release."""

    __tablename__ = "sdlc_runs"
    __table_args__ = (Index("ix_sdlc_runs_user_created", "user_id", "created_at"),)
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(12), default="feature")  # feature | bugfix | refactor | review
    title: Mapped[str] = mapped_column(String(300))
    goal: Mapped[str] = mapped_column(Text, default="")
    repo: Mapped[str] = mapped_column(String(200))  # owner/name
    base_branch: Mapped[str] = mapped_column(String(200), default="")
    branch: Mapped[str] = mapped_column(String(250), default="")
    autonomy: Mapped[str] = mapped_column(String(12), default="guided")  # guided | autopilot
    auto_merge: Mapped[bool] = mapped_column(Boolean, default=False)
    deploy_hook_ciphertext: Mapped[str | None] = mapped_column(Text)
    # queued | running | waiting_user | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(14), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(20), default="spec")
    stages: Mapped[list] = mapped_column(JSONType, default=list)  # [{key, status, summary, output, started_at, finished_at}]
    log: Mapped[list] = mapped_column(JSONType, default=list)  # [{at, level, message}] (capped)
    context: Mapped[dict] = mapped_column(JSONType, default=dict)  # working memory between stages (spec, design, notes…)
    issue_url: Mapped[str] = mapped_column(String(500), default="")
    pr_number: Mapped[int | None] = mapped_column(Integer)
    pr_url: Mapped[str] = mapped_column(String(500), default="")
    head_sha: Mapped[str] = mapped_column(String(64), default="")
    merge_sha: Mapped[str] = mapped_column(String(64), default="")
    release_url: Mapped[str] = mapped_column(String(500), default="")
    gate: Mapped[str | None] = mapped_column(String(20))  # plan | merge: what the run waits for
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # worker lease (one worker per run)
    usage: Mapped[dict] = mapped_column(JSONType, default=dict)
    model: Mapped[str] = mapped_column(String(120), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    report: Mapped[dict | None] = mapped_column(JSONType)  # {goal, rationale, validation, handoff}


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
    snapshot_name: Mapped[str | None] = mapped_column(String(200))  # ORBIT base snapshot applied (reference only)
    snapshot_version: Mapped[int | None] = mapped_column(Integer)
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


class EmailCode(Base):
    """One-time code e-mailed to prove ownership of an address (sign-up, password reset). Only its hash is kept."""

    __tablename__ = "email_codes"
    id: Mapped[uuid.UUID] = _pk()
    email: Mapped[str] = mapped_column(String(320), index=True)
    purpose: Mapped[str] = mapped_column(String(20))  # signup | reset
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DevIdentity(Base):
    """Password accounts for development and tests (``NOVA_AUTH_MODE=dev``); production accounts live in Keycloak."""

    __tablename__ = "dev_identities"
    id: Mapped[uuid.UUID] = _pk()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Goal(Base):
    """A result the user entrusts to NOVA ("Ship Checkout v2 by 15 December"). NOVA plans milestones and runs them."""

    __tablename__ = "goals"
    __table_args__ = (Index("ix_goals_user_status", "user_id", "status"),)
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    outcome: Mapped[str] = mapped_column(Text, default="")  # the expected result, in the user's words
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # planning | proposed | active | paused | completed | archived
    status: Mapped[str] = mapped_column(String(20), default="planning")
    autonomy: Mapped[str] = mapped_column(String(30), default="execute_with_approval")
    lang: Mapped[str] = mapped_column(String(5), default="en")
    plan: Mapped[dict] = mapped_column(JSONType, default=dict)  # {summary, assumptions, milestones: [...]}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Routine(Base):
    """Work that should not need to be asked twice: runs on a schedule (or on demand) as a NOVA task."""

    __tablename__ = "routines"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200))
    instructions: Mapped[str] = mapped_column(Text)  # the request NOVA runs each time
    skill_ids: Mapped[list] = mapped_column(JSONType, default=list)
    template: Mapped[str | None] = mapped_column(String(60))
    # {"kind": "daily" | "weekly" | "weekdays" | "monthly", "time": "08:30", "days": [0-6], "day": 1, "tz": "Europe/Paris"}
    schedule: Mapped[dict] = mapped_column(JSONType, default=dict)
    autonomy: Mapped[str] = mapped_column(String(30), default="execute_automatically")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LearnedSkill(Base):
    """A workflow NOVA learned by watching the user (Teach NOVA): existing Skills chained with the user's own steps."""

    __tablename__ = "learned_skills"
    __table_args__ = (UniqueConstraint("user_id", "slug"),)
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    steps: Mapped[list] = mapped_column(JSONType, default=list)  # [{title, instruction, skill_id | null}]
    source: Mapped[dict] = mapped_column(JSONType, default=dict)  # {observed: [...], started_at, finished_at}
    lang: Mapped[str] = mapped_column(String(5), default="en")
    uses: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentPolicy(Base):
    """A versioned set of lessons an agent learned from FORGE (domain/learning.py, docs/TRAINING.md).

    ``status``: ``candidate`` (under experiment) → ``active`` (applied to every execution) → ``retired``;
    or ``rejected`` when FORGE did not validate it. One ``active`` policy per agent at most.
    """

    __tablename__ = "agent_policies"
    __table_args__ = (UniqueConstraint("agent", "version"), Index("ix_agent_policies_agent_status", "agent", "status"))
    id: Mapped[uuid.UUID] = _pk()
    agent: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="candidate")
    standards: Mapped[list] = mapped_column(JSONType, default=list)
    skills: Mapped[dict] = mapped_column(JSONType, default=dict)  # {skill_id: [lesson]}
    recommendations: Mapped[list] = mapped_column(JSONType, default=list)  # FORGE advice a prompt cannot apply
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    cycle_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    forge_agent_version_id: Mapped[str | None] = mapped_column(String(64))
    # Fingerprint of the FORGE version body: a new model, Skill catalog or budget registers a new version
    forge_version_key: Mapped[str | None] = mapped_column(String(64))
    score: Mapped[float | None] = mapped_column(Float)  # FORGE composite score when it was validated
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _created()
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TrainingCycle(Base):
    """One FORGE training cycle of an agent over all of its Skills (services/training.py).

    ``queued`` → ``evaluating`` (baseline runs) → ``experimenting`` (baseline vs candidate) →
    ``promoted`` | ``rejected`` | ``no_change`` | ``failed`` | ``cancelled``.
    """

    __tablename__ = "training_cycles"
    __table_args__ = (Index("ix_training_cycles_agent_created", "agent", "created_at"),)
    id: Mapped[uuid.UUID] = _pk()
    agent: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    trigger: Mapped[str] = mapped_column(String(20), default="manual")  # manual | scheduled
    requested_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    baseline_policy_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    candidate_policy_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    skills: Mapped[list] = mapped_column(JSONType, default=list)  # [{id, version, scenario_id}]
    baseline_runs: Mapped[list] = mapped_column(JSONType, default=list)  # [{run_id, skill_id}]
    forge_experiment_id: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSONType, default=dict)  # baseline scores, decision, deltas
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
