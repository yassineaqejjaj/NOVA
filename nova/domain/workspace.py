"""Workspace identifiers and the keys that carry them (ADR 001 §5 and §9, NOV-107). Pure: no database."""

from __future__ import annotations

import uuid
from typing import Any

from nova.config import get_settings


def as_uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _fingerprint(workspace_id: uuid.UUID | str | None) -> str | None:
    """Short, stable form of a non-default workspace id; None for the default one (its keys are the historical ones)."""
    found = as_uuid(workspace_id) if workspace_id else None
    if found is None or found == get_settings().default_workspace_id:
        return None
    return found.hex[:16]


def thread_id(task_id: uuid.UUID | str, workspace_id: uuid.UUID | str | None) -> str:
    """LangGraph checkpoint thread of a run. The default workspace keeps the bare task id: existing checkpoints stay
    reachable. The workspace is a property of the row, not of the mode: flipping ``NOVA_WORKSPACE_ENFORCEMENT`` never
    moves a thread."""
    fingerprint = _fingerprint(workspace_id)
    return f"{fingerprint}:{task_id}" if fingerprint else str(task_id)


def outbox_key(task_id: uuid.UUID | str, workspace_id: uuid.UUID | str | None) -> str:
    """Deduplication key of a FORGE capture in NOVA's outbox (``nova-task:<id>``; the workspace joins it outside the
    default one). The ``external_id`` FORGE sees stays ``nova-task:<id>``: a task id is unique everywhere."""
    fingerprint = _fingerprint(workspace_id)
    return f"nova-task:{fingerprint}:{task_id}" if fingerprint else f"nova-task:{task_id}"
