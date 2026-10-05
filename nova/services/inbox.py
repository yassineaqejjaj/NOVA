"""NOVA Inbox: NOVA works, filters, and brings to the user only what needs a human.

Five kinds: ``decision`` (questions, plans and milestones waiting for the user), ``validation`` (deliverables to
review), ``anomaly`` (failures, blocked milestones, deliverables with reservations, ORBIT conflicts), ``suggestion``
(what NOVA recommends doing) and ``result`` (what routines produced). Built from Today's recommendations plus goals,
routines and the Validation agent's reports; dismissing reuses the Home's dismissed list.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.i18n import Lang
from nova.infra.db import aware, utcnow
from nova.infra.models import Artifact, Goal, Routine, Task, TaskStep
from nova.services.goals import OPEN_GOALS, milestones

KINDS = ("decision", "validation", "anomaly", "suggestion", "result")

T = {
    "plan_title": {"en": "NOVA’s plan for “{goal}” is ready", "fr": "Le plan de NOVA pour « {goal} » est prêt"},
    "plan_sub": {"en": "{n} milestones — approve to start the mission.", "fr": "{n} jalons — approuvez pour lancer la mission."},
    "observe_sub": {
        "en": "Observation mode: NOVA recommends this plan; nothing runs until you approve it.",
        "fr": "Mode observation : NOVA recommande ce plan ; rien ne s’exécute avant votre accord.",
    },
    "human_title": {"en": "{goal}: {milestone}", "fr": "{goal} : {milestone}"},
    "human_sub": {
        "en": "This step needs you or the team. Mark it done when it is, or let NOVA prepare it.",
        "fr": "Cette étape vous revient, à vous ou à l’équipe. Marquez-la comme faite, ou laissez NOVA la préparer.",
    },
    "ready_sub": {
        "en": "NOVA is ready to run the next step of this goal.",
        "fr": "NOVA est prêt à lancer l’étape suivante de ce goal.",
    },
    "blocked_sub": {"en": "This milestone failed. Retry it or skip it.", "fr": "Ce jalon a échoué. Relancez-le ou passez-le."},
    "validate_title": {"en": "{title} is ready", "fr": "{title} est prêt"},
    "validate_sub": {
        "en": "Produced by NOVA for “{origin}”. Review it, then validate or ask for a change.",
        "fr": "Produit par NOVA pour « {origin} ». Relisez-le, puis validez ou demandez une modification.",
    },
    "reserve_title": {"en": "{title} delivered with reservations", "fr": "{title} livré avec réserves"},
    "reserve_sub": {
        "en": "The Validation agent flagged points to review.",
        "fr": "L’agent Validation a signalé des points à revoir.",
    },
    "routine_title": {"en": "{routine} — result ready", "fr": "{routine} — résultat disponible"},
    "routine_sub": {"en": "Routine run of {when}.", "fr": "Exécution de la routine du {when}."},
    "approve": {"en": "Approve the plan", "fr": "Approuver le plan"},
    "view_plan": {"en": "View the plan", "fr": "Voir le plan"},
    "done": {"en": "Mark as done", "fr": "Marquer comme fait"},
    "prepare": {"en": "Let NOVA prepare it", "fr": "Laisser NOVA préparer"},
    "start": {"en": "Start", "fr": "Lancer"},
    "retry": {"en": "Retry", "fr": "Relancer"},
    "skip": {"en": "Skip", "fr": "Passer"},
    "validate": {"en": "Validate", "fr": "Valider"},
    "change": {"en": "Ask for a change", "fr": "Demander une modification"},
    "open": {"en": "Open", "fr": "Ouvrir"},
    "view_result": {"en": "View the result", "fr": "Voir le résultat"},
    "ignore": {"en": "Ignore", "fr": "Ignorer"},
}


def tr(lang: Lang, key: str, **values: Any) -> str:
    return T[key]["fr" if lang == "fr" else "en"].format(**values)


def _kind_of_recommendation(rec: dict[str, Any]) -> str:
    rid = str(rec.get("id", ""))
    if rid.startswith("nova:waiting"):
        return "validation" if rec.get("waiting_kind") == "approval" else "decision"
    if rid.startswith("nova:failed") or rec.get("risk") or "conflict" in rid:
        return "anomaly"
    return "suggestion"


def confidence_from_report(report: dict[str, Any] | None, forge_score: float | None = None) -> dict[str, Any] | None:
    """NOVA confidence of a deliverable: the Validation agent's checks and criteria, and FORGE's score when known."""
    validation = (report or {}).get("validation")
    if not validation and forge_score is None:
        return None
    dims: dict[str, float] = {}
    if validation:
        checks = validation.get("checks") or []

        def ratio(keys: tuple[str, ...]) -> float | None:
            sel = [c for c in checks if c.get("key") in keys]
            return round(100 * sum(1 for c in sel if c.get("passed")) / len(sel)) if sel else None

        grounding = ratio(("citation_required",))
        completeness = ratio(("filled", "sections_present"))
        safety = ratio(("no_pii", "max_length"))
        criteria = validation.get("criteria") or []
        consistency = round(100 * sum(1 for c in criteria if c.get("passed")) / len(criteria)) if criteria else None
        for key, value in (
            ("grounding", grounding),
            ("completeness", completeness),
            ("consistency", consistency),
            ("safety", safety),
        ):
            if value is not None:
                dims[key] = value
    if forge_score is not None:
        dims["quality"] = round(100 * forge_score if forge_score <= 1 else forge_score)
    if not dims:
        return None
    score = round(sum(dims.values()) / len(dims))
    if validation and validation.get("status") == "warning":
        score = min(score, 69)
    level = "high" if score >= 85 else "medium" if score >= 70 else "low"
    return {
        "score": score,
        "level": level,
        "dimensions": dims,
        "status": (validation or {}).get("status"),
        "evaluated_by": [*(["validation"] if validation else []), *(["forge"] if forge_score is not None else [])],
    }


async def collect(
    session: AsyncSession,
    user_id: uuid.UUID,
    lang: Lang,
    recommendations: list[dict[str, Any]],
    dismissed: set[str],
    names: dict[uuid.UUID, str],
) -> list[dict[str, Any]]:
    now = utcnow()
    items: list[dict[str, Any]] = []
    for rec in recommendations:
        items.append({**rec, "kind": _kind_of_recommendation(rec)})

    # --- Goals: plans to approve, human milestones, ready / blocked steps -----------------------------
    goals = (await session.scalars(select(Goal).where(Goal.user_id == user_id, Goal.status.in_(OPEN_GOALS)))).all()
    for goal in goals:
        project = names.get(goal.project_id) if goal.project_id else None
        base = {
            "source": "nova",
            "project_id": str(goal.project_id) if goal.project_id else None,
            "project_name": project,
            "goal_id": str(goal.id),
            "at": (goal.updated_at or goal.created_at).isoformat(),
        }
        href = f"/goals?goal={goal.id}"
        if goal.status == "proposed":
            items.append(
                {
                    **base,
                    "id": f"goal:plan:{goal.id}",
                    "kind": "decision",
                    "urgent": True,
                    "title": tr(lang, "plan_title", goal=goal.title),
                    "subtitle": tr(lang, "observe_sub")
                    if goal.autonomy == "observe"
                    else tr(lang, "plan_sub", n=len(milestones(goal))),
                    "actions": [
                        {"kind": "goal", "action": "approve", "label": tr(lang, "approve"), "goal_id": str(goal.id)},
                        {"kind": "review", "label": tr(lang, "view_plan"), "href": href},
                    ],
                }
            )
            continue
        if goal.status != "active":
            continue
        for m in milestones(goal):
            status, mid = m.get("status"), m.get("id")
            if status == "waiting" and m.get("kind") == "human":
                items.append(
                    {
                        **base,
                        "id": f"goal:human:{goal.id}:{mid}",
                        "kind": "decision",
                        "urgent": True,
                        "milestone_id": mid,
                        "title": tr(lang, "human_title", goal=goal.title, milestone=m.get("title", "")),
                        "subtitle": m.get("goal") or tr(lang, "human_sub"),
                        "actions": [
                            {
                                "kind": "goal",
                                "action": "done",
                                "label": tr(lang, "done"),
                                "goal_id": str(goal.id),
                                "milestone_id": mid,
                            },
                            {"kind": "review", "label": tr(lang, "open"), "href": href},
                        ],
                    }
                )
            elif status == "ready":
                items.append(
                    {
                        **base,
                        "id": f"goal:ready:{goal.id}:{mid}",
                        "kind": "decision",
                        "milestone_id": mid,
                        "title": tr(lang, "human_title", goal=goal.title, milestone=m.get("title", "")),
                        "subtitle": tr(lang, "ready_sub"),
                        "actions": [
                            {
                                "kind": "goal",
                                "action": "start",
                                "label": tr(lang, "start"),
                                "goal_id": str(goal.id),
                                "milestone_id": mid,
                            },
                            {
                                "kind": "goal",
                                "action": "skip",
                                "label": tr(lang, "skip"),
                                "goal_id": str(goal.id),
                                "milestone_id": mid,
                            },
                        ],
                    }
                )
            elif status == "blocked":
                items.append(
                    {
                        **base,
                        "id": f"goal:blocked:{goal.id}:{mid}",
                        "kind": "anomaly",
                        "risk": True,
                        "milestone_id": mid,
                        "title": tr(lang, "human_title", goal=goal.title, milestone=m.get("title", "")),
                        "subtitle": m.get("note") or tr(lang, "blocked_sub"),
                        "actions": [
                            {
                                "kind": "goal",
                                "action": "retry",
                                "label": tr(lang, "retry"),
                                "goal_id": str(goal.id),
                                "milestone_id": mid,
                            },
                            {
                                "kind": "goal",
                                "action": "skip",
                                "label": tr(lang, "skip"),
                                "goal_id": str(goal.id),
                                "milestone_id": mid,
                            },
                        ],
                    }
                )

    # --- Deliverables of goals and routines (last 7 days): validate, or review the reservations -----------
    recent = (
        await session.execute(
            select(TaskStep, Task, Artifact)
            .join(Task, Task.id == TaskStep.task_id)
            .join(Artifact, Artifact.id == TaskStep.artifact_id)
            .where(
                Task.user_id == user_id,
                Task.origin.in_(("goal", "routine")),
                TaskStep.status == "completed",
                Task.finished_at >= now - timedelta(days=7),
            )
            .order_by(Task.finished_at.desc())
            .limit(20)
        )
    ).all()
    for step, task, artifact in recent:
        report = step.report or {}
        confidence = confidence_from_report(report)
        origin = task.objective.split("\n")[0].split(" — ")[0].lstrip("/").split(" ", 1)[-1][:80]
        base = {
            "source": "nova",
            "project_id": str(task.project_id) if task.project_id else None,
            "project_name": names.get(task.project_id) if task.project_id else None,
            "artifact_id": str(artifact.id),
            "task_id": str(task.id),
            "at": (task.finished_at or task.created_at).isoformat(),
            "confidence": confidence,
        }
        if (report.get("validation") or {}).get("status") == "warning":
            items.append(
                {
                    **base,
                    "id": f"artifact:reserve:{artifact.id}:{artifact.current_version}",
                    "kind": "anomaly",
                    "risk": True,
                    "title": tr(lang, "reserve_title", title=artifact.title),
                    "subtitle": tr(lang, "reserve_sub"),
                    "actions": [
                        {"kind": "review", "label": tr(lang, "open"), "href": f"/artifacts/{artifact.id}"},
                        {"kind": "ignore", "label": tr(lang, "ignore")},
                    ],
                }
            )
        else:
            items.append(
                {
                    **base,
                    "id": f"artifact:validate:{artifact.id}:{artifact.current_version}",
                    "kind": "validation",
                    "title": tr(lang, "validate_title", title=artifact.title),
                    "subtitle": tr(lang, "validate_sub", origin=origin),
                    "actions": [
                        {"kind": "validate", "label": tr(lang, "validate"), "artifact_id": str(artifact.id)},
                        {"kind": "review", "label": tr(lang, "change"), "href": f"/artifacts/{artifact.id}"},
                    ],
                }
            )

    # --- Routine results (last 3 days) ------------------------------------------------------------------
    runs = (
        await session.execute(
            select(Task, Routine)
            .join(Routine, Routine.last_task_id == Task.id)
            .where(
                Task.user_id == user_id,
                Task.origin == "routine",
                Task.status == "completed",
                Task.finished_at >= now - timedelta(days=3),
            )
        )
    ).all()
    for task, routine in runs:
        when = aware(task.finished_at or task.created_at).astimezone(ZoneInfo("Europe/Paris")).strftime("%d/%m %H:%M")
        items.append(
            {
                "id": f"routine:result:{task.id}",
                "kind": "result",
                "source": "nova",
                "routine_id": str(routine.id),
                "task_id": str(task.id),
                "project_id": str(task.project_id) if task.project_id else None,
                "project_name": names.get(task.project_id) if task.project_id else None,
                "title": tr(lang, "routine_title", routine=routine.name),
                "subtitle": tr(lang, "routine_sub", when=when),
                "at": (task.finished_at or task.created_at).isoformat(),
                "actions": [
                    {"kind": "review", "label": tr(lang, "view_result"), "href": f"/c/{task.conversation_id}"},
                    {"kind": "ignore", "label": tr(lang, "ignore")},
                ],
            }
        )

    seen: set[str] = set()
    unique = []
    for item in items:
        if item["id"] in dismissed or item["id"] in seen:
            continue
        seen.add(item["id"])
        unique.append(item)
    order = {k: i for i, k in enumerate(KINDS)}
    unique.sort(key=lambda i: (order.get(i["kind"], 9), not i.get("urgent"), str(i.get("at", ""))), reverse=False)
    return unique


def counts(items: list[dict[str, Any]]) -> dict[str, int]:
    result = {k: 0 for k in KINDS}
    for item in items:
        result[item["kind"]] = result.get(item["kind"], 0) + 1
    result["total"] = len(items)
    return result
