"""All NOVA enumerations (mirrored in ``apps/web/src/lib/enums.ts``)."""

from __future__ import annotations

from enum import IntEnum, StrEnum


class TaskStatus(StrEnum):
    queued = "queued"
    scheduled = "scheduled"
    running = "running"
    waiting_user = "waiting_user"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


ACTIVE_TASK_STATUSES = frozenset({TaskStatus.queued, TaskStatus.running, TaskStatus.waiting_user})
TERMINAL_TASK_STATUSES = frozenset({TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled})


class NovaPhase(StrEnum):
    """Visible NOVA state (``listening`` is a client-side state of the composer)."""

    idle = "idle"
    retrieving_context = "retrieving_context"
    planning = "planning"
    executing = "executing"
    waiting_user = "waiting_user"
    completed = "completed"
    failed = "failed"


class StepStatus(StrEnum):
    pending = "pending"
    running = "running"
    waiting_user = "waiting_user"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


class AutonomyMode(StrEnum):
    suggest = "suggest"
    assist = "assist"
    execute_with_approval = "execute_with_approval"
    execute_automatically = "execute_automatically"


class IntentKind(StrEnum):
    run_workflow = "run_workflow"  # produce product work through one or more Skills
    edit_artifact = "edit_artifact"  # modify part of an existing Artifact
    explain_provenance = "explain_provenance"  # "why did you include …?"
    question = "question"  # answer from context, no Artifact
    smalltalk = "smalltalk"


class SkillCategory(StrEnum):
    strategy = "strategy"
    discovery = "discovery"
    prioritization = "prioritization"
    definition = "definition"
    delivery = "delivery"
    analysis = "analysis"
    communication = "communication"
    artifact = "artifact"  # system Skills (Artifact editing)


class ExecutionOrigin(StrEnum):
    interactive = "interactive"
    forge_protocol = "forge_protocol"  # FORGE evaluation call (NOVA Agent Protocol)
    scheduled = "scheduled"


class AuthorType(StrEnum):
    user = "user"
    nova = "nova"


class ProjectRole(StrEnum):
    owner = "owner"
    editor = "editor"
    viewer = "viewer"


PROJECT_ROLE_RANK = {ProjectRole.viewer: 1, ProjectRole.editor: 2, ProjectRole.owner: 3}


def role_at_least(role: ProjectRole | str | None, minimum: ProjectRole) -> bool:
    if role is None:
        return False
    return PROJECT_ROLE_RANK[ProjectRole(role)] >= PROJECT_ROLE_RANK[minimum]


class Classification(IntEnum):
    """Aligned with ORBIT and FORGE (C0 → C3)."""

    public = 0
    internal = 1
    confidential = 2
    secret = 3


CLASSIFICATION_LABELS = {0: "C0 · Public", 1: "C1 · Internal", 2: "C2 · Confidential", 3: "C3 · Secret"}


class FeedbackRating(StrEnum):
    useful = "useful"
    not_useful = "not_useful"


class SectionKind(StrEnum):
    rich_text = "rich_text"
    items = "items"


class BlockType(StrEnum):
    text = "text"
    plan = "plan"
    workflow = "workflow"
    question = "question"
    checklist = "checklist"
    task = "task"
    artifact = "artifact"
    table = "table"
    decision = "decision"
    context_sources = "context_sources"
    tool_execution = "tool_execution"
    progress = "progress"
    warning = "warning"
    error = "error"
    citations = "citations"


class EventType(StrEnum):
    status = "status"  # NOVA phase changed
    progress = "progress"  # operational summary line (never raw reasoning)
    block = "block"  # message block upserted
    task = "task"  # task / step status changed
    done = "done"
    error = "error"
