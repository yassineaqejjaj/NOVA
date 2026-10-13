"""Time Machine: put a run and one of its what-if replays side by side (services/replay.py creates the replays).

Everything shown comes from the two runs themselves — the run manifest, usage, and the Artifacts each produced —
so the comparison says what the change did to the result, the cost and the time, and nothing more.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.artifacts.registry import get_artifact_registry
from nova.domain.artifacts import ArtifactContent, compare_contents, empty_content, section_plain_text
from nova.domain.permissions import Principal
from nova.domain.time_machine import pair_by_type, relative_change, word_count
from nova.infra.db import aware
from nova.infra.models import Artifact, ArtifactVersion, Task
from nova.services.access import require_task, within_clearance
from nova.services.replay import ReplayError


def _seconds(task: Task) -> int | None:
    start, end = aware(task.started_at), aware(task.finished_at)
    return int((end - start).total_seconds()) if start and end and end >= start else None


def _tokens(task: Task) -> int | None:
    usage = task.usage or {}
    if "input_tokens" not in usage and "output_tokens" not in usage:
        return None
    return int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))


def _side(task: Task) -> dict[str, Any]:
    manifest = task.run_manifest or {}
    context = manifest.get("context") or {}
    policies = manifest.get("policies") or {}
    return {
        "id": str(task.id),
        "status": task.status,
        "error": task.error,
        "model": task.model or manifest.get("model"),
        "tokens": _tokens(task),
        "duration_seconds": _seconds(task),
        "context_items": context.get("items"),
        "context_sufficiency": context.get("sufficiency"),
        "snapshot": context.get("snapshot_id"),
        "policies": {agent: p.get("version") for agent, p in policies.items()},
        "overrides": (task.input or {}).get("replay_overrides") or manifest.get("overrides") or {},
    }


async def _artifacts(session: AsyncSession, task: Task, principal: Principal) -> list[tuple[str, tuple[str, ArtifactContent]]]:
    rows = (
        await session.scalars(
            select(Artifact).where(Artifact.task_id == task.id, within_clearance(principal)).order_by(Artifact.created_at)
        )
    ).all()
    found = []
    for artifact in rows:
        version = await session.scalar(
            select(ArtifactVersion).where(
                ArtifactVersion.artifact_id == artifact.id, ArtifactVersion.version == artifact.current_version
            )
        )
        if version is not None:
            found.append((artifact.type, (str(artifact.id), ArtifactContent.model_validate(version.content))))
    return found


def _words(content: ArtifactContent | None) -> int:
    return sum(word_count(section_plain_text(s)) for s in content.sections.values()) if content else 0


def _artifact_diff(
    kind: str, left: tuple[str, ArtifactContent] | None, right: tuple[str, ArtifactContent] | None
) -> dict[str, Any]:
    template = get_artifact_registry().get(kind)
    base = left[1] if left else empty_content(template, "")
    other = right[1] if right else empty_content(template, "")
    sections = [d for d in compare_contents(base, other) if d.status != "unchanged"]
    return {
        "type": kind,
        "title": other.title or base.title,
        "original_id": left[0] if left else None,
        "replay_id": right[0] if right else None,
        "words": {"original": _words(left[1] if left else None), "replay": _words(right[1] if right else None)},
        "sections": [
            {
                "key": d.key,
                "status": d.status,
                "before": d.before_text,
                "after": d.after_text,
                "added_items": len(d.added_items),
                "removed_items": len(d.removed_items),
                "changed_items": len(d.changed_items),
            }
            for d in sections
        ],
    }


async def compare(session: AsyncSession, principal: Principal, task_id: str, replay_id: str) -> dict[str, Any]:
    original = await require_task(session, task_id, principal)
    replay = await require_task(session, replay_id, principal)
    if replay.replay_of != original.id:
        raise ReplayError("not_a_replay", "This run is not a replay of the original.")
    left, right = _side(original), _side(replay)
    pairs = pair_by_type(await _artifacts(session, original, principal), await _artifacts(session, replay, principal))
    diffs = [_artifact_diff(kind, a, b) for kind, a, b in pairs]
    return {
        "original": left,
        "replay": right,
        "delta": {
            "tokens": relative_change(left["tokens"], right["tokens"]),
            "duration": relative_change(left["duration_seconds"], right["duration_seconds"]),
            "context_items": relative_change(left["context_items"], right["context_items"]),
        },
        "artifacts": diffs,
        "sections_changed": sum(len(d["sections"]) for d in diffs),
    }
