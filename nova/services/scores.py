"""Execution health, deliverable quality and business gain of a settled run, from what NOVA stored (domain/scores.py)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.artifacts.registry import get_artifact_registry
from nova.domain.artifacts import ArtifactContent
from nova.domain.permissions import Principal
from nova.domain.scores import (
    BusinessSignals,
    DeliverableSignals,
    Score,
    business_gain,
    deliverable_quality,
    execution_health,
)
from nova.infra.models import Artifact, ArtifactVersion, Feedback, SkillExecution, Task, TaskStep
from nova.services.access import within_clearance

SETTLED = ("completed", "failed")


def _view(score: Score) -> dict[str, Any]:
    return {"score": score.score, "checks": [c.model_dump() for c in score.checks]}


async def task_scores(session: AsyncSession, task: Task, principal: Principal) -> dict[str, Any] | None:
    """The three indicators of a settled run (``None`` while it runs). The Artifacts counted are those the viewer may read."""
    if task.status not in SETTLED:
        return None
    steps = (await session.scalars(select(TaskStep).where(TaskStep.task_id == task.id))).all()
    executions = (await session.scalars(select(SkillExecution).where(SkillExecution.task_id == task.id))).all()
    artifacts = (await session.scalars(select(Artifact).where(Artifact.task_id == task.id, within_clearance(principal)))).all()
    feedback = (
        await session.scalars(select(Feedback).where(Feedback.task_id == task.id).order_by(Feedback.created_at.desc()).limit(1))
    ).first()
    errors = sum(1 for s in steps if s.status == "failed") + (1 if task.status == "failed" else 0)
    health = execution_health(
        completed=task.status == "completed",
        all_skills_completed=all(e.status == "completed" for e in executions),
        error_count=errors,
    )

    sections = empty = 0
    versions = human = 0
    for artifact in artifacts:
        rows = (await session.scalars(select(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact.id))).all()
        versions += len(rows)
        human += sum(1 for v in rows if v.author_type == "user")
        current = next((v for v in rows if v.version == artifact.current_version), None)
        if current is None:
            continue
        content = ArtifactContent.model_validate(current.content)
        defined = get_artifact_registry().get(artifact.type).sections
        sections += len(defined)
        empty += sum(1 for s in defined if (sec := content.sections.get(s.key)) is None or sec.is_empty())
    dropped = [d for e in executions if (d := (e.output or {}).get("dropped_citations")) is not None]
    validation = [v["status"] for s in steps if (v := (s.report or {}).get("validation")) and v.get("status")]
    useful = None if feedback is None else feedback.rating == "useful"

    quality = deliverable_quality(
        DeliverableSignals(
            artifacts=len(artifacts),
            sections=sections,
            empty_sections=empty if artifacts else None,
            validation=validation,
            dropped_citations=sum(dropped) if dropped else None,
            useful=useful,
        )
    )
    accepted = useful if useful is not None else (True if any(a.status in ("in_review", "final") for a in artifacts) else None)
    gain = business_gain(BusinessSignals(accepted=accepted, versions=versions, human_versions=human))
    return {"execution_health": health, "deliverable_quality": _view(quality), "business_gain": _view(gain)}
