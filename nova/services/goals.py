"""Goals: the user gives NOVA a result to reach; NOVA plans milestones and carries them out as a mission.

Each Skill milestone runs as a NOVA task in the goal's own conversation (so its questions, approvals and deliverables
appear where the user expects them, and in the Inbox). The autonomy of the goal decides how far NOVA goes alone:

* ``observe``  — NOVA builds the plan and recommends; nothing runs;
* ``suggest``  — the plan, then each milestone, waits for the user's go;
* ``execute_with_approval`` — milestones run one after the other; changes to existing Artifacts wait for approval;
* ``execute_automatically`` — NOVA runs the whole plan; it still stops for questions and human milestones.

Milestones move forward when a task settles (``on_task_settled``) and on the beat's minute tick (safety net).
"""

from __future__ import annotations

import copy
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from nova.agent import prompts
from nova.domain.enums import AutonomyMode, TaskStatus
from nova.domain.outputs import GoalPlanOutput
from nova.domain.permissions import Principal
from nova.infra.db import aware, utcnow
from nova.infra.models import Conversation, Goal, Project, Task, User
from nova.services import providers
from nova.services.access import AccessDenied, project_role
from nova.services.audit import audit
from nova.services.conversations import ComposerInput, create_conversation, submit
from nova.services.users import principal_for
from nova.skills.registry import get_skill_registry
from nova.skills.router import SkillRouter

log = logging.getLogger(__name__)

RUNNING = {"working", "waiting"}
OPEN_GOALS = ("planning", "proposed", "active", "paused")


class GoalError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --- Views --------------------------------------------------------------------------------------------


def milestones(goal: Goal) -> list[dict[str, Any]]:
    """A copy: changes are saved by assigning the plan back (``_save``), never by mutating the loaded JSON."""
    return copy.deepcopy(list((goal.plan or {}).get("milestones") or []))


def _save(goal: Goal, items: list[dict[str, Any]]) -> None:
    goal.plan = {**copy.deepcopy(goal.plan or {}), "milestones": items}
    flag_modified(goal, "plan")


def progress(goal: Goal) -> dict[str, int]:
    items = [m for m in milestones(goal) if m.get("status") != "skipped"]
    done = sum(1 for m in items if m.get("status") == "done")
    return {"done": done, "total": len(items), "percent": round(100 * done / len(items)) if items else 0}


def mission_state(goal: Goal) -> str:
    """working | waiting (for the user) | blocked | idle | done — what the goal's mission is doing now."""
    if goal.status == "completed":
        return "done"
    states = [m.get("status") for m in milestones(goal)]
    if goal.status == "proposed" or "waiting" in states or "ready" in states:
        return "waiting"
    if "blocked" in states:
        return "blocked"
    if goal.status == "active" and "working" in states:
        return "working"
    return "idle"


def goal_view(goal: Goal, *, project_name: str | None = None) -> dict[str, Any]:
    items = milestones(goal)
    current = next((m for m in items if m.get("status") in ("working", "waiting", "ready", "blocked")), None)
    upcoming = next((m for m in items if m.get("status") == "pending"), None)
    return {
        "id": str(goal.id),
        "title": goal.title,
        "outcome": goal.outcome,
        "due_date": aware(goal.due_date).isoformat() if goal.due_date else None,
        "status": goal.status,
        "autonomy": goal.autonomy,
        "project_id": str(goal.project_id) if goal.project_id else None,
        "project_name": project_name,
        "conversation_id": str(goal.conversation_id) if goal.conversation_id else None,
        "summary": (goal.plan or {}).get("summary", ""),
        "assumptions": (goal.plan or {}).get("assumptions", []),
        "milestones": items,
        "progress": progress(goal),
        "mission": mission_state(goal),
        "current": current,
        "next": upcoming,
        "created_at": aware(goal.created_at).isoformat(),
        "updated_at": aware(goal.updated_at).isoformat() if goal.updated_at else None,
        "completed_at": aware(goal.completed_at).isoformat() if goal.completed_at else None,
    }


# --- Planning -------------------------------------------------------------------------------------------


def _slug(text: str, index: int) -> str:
    return f"m{index}-" + (re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:28] or "step")


async def plan_goal(goal: Goal, project_name: str | None) -> dict[str, Any]:
    """NOVA's own plan for the goal (one model call over the routed Skill catalog)."""
    registry = get_skill_registry()
    router = SkillRouter(registry)
    text = f"{goal.title}\n{goal.outcome}"
    routed = [c.skill for c in router.candidates(text, limit=14)]
    defaults = [
        "problem-framing",
        "feedback-synthesis",
        "prd",
        "user-story-generation",
        "acceptance-criteria",
        "release-planning",
        "risk-analysis",
        "stakeholder-brief",
    ]
    candidates = routed + [registry.get(s) for s in defaults if registry.has(s) and all(c.id != s for c in routed)]
    result = await (await providers.llm_for_user(str(goal.user_id))).structured_output(
        prompts.goal_plan_messages(
            title=goal.title,
            outcome=goal.outcome,
            due=goal.due_date.date().isoformat() if goal.due_date else None,
            today=datetime.now(UTC).date().isoformat(),
            lang=goal.lang,
            candidates=candidates,
            project=project_name,
        ),
        GoalPlanOutput,
    )
    plan: GoalPlanOutput = result.value
    allowed = {s.id for s in candidates}
    items: list[dict[str, Any]] = []
    used: set[str] = set()
    for i, m in enumerate(plan.milestones):
        kind = m.kind if not (m.kind == "skill" and (m.skill_id not in allowed or m.skill_id in used)) else "human"
        skill = registry.get(m.skill_id) if kind == "skill" and m.skill_id else None
        if skill:
            used.add(skill.id)
        items.append(
            {
                "id": _slug(m.title, i + 1),
                "title": m.title,
                "kind": kind,
                "skill_id": skill.id if skill else None,
                "agent": skill.agent.value if skill else None,
                "goal": m.goal,
                "rationale": m.rationale,
                "status": "pending",
                "task_id": None,
                "artifact_ids": [],
                "started_at": None,
                "finished_at": None,
                "note": "",
            }
        )
    if not any(m["kind"] == "skill" for m in items):
        raise GoalError("plan_failed", "NOVA could not find Skills to reach this goal. Rephrase it as a result.")
    return {"summary": plan.summary, "assumptions": plan.assumptions, "milestones": items}


async def create_goal(
    session: AsyncSession,
    principal: Principal,
    *,
    title: str,
    outcome: str,
    due_date: datetime | None,
    project_id: str | None,
    autonomy: AutonomyMode,
    lang: str,
) -> tuple[Goal, list[str]]:
    """Creates the goal, plans it and (depending on autonomy) starts the mission. Returns task ids to dispatch."""
    pid = uuid.UUID(project_id) if project_id else None
    project = await session.get(Project, pid) if pid else None
    if pid and (
        project is None or (await project_role(session, pid, uuid.UUID(principal.user_id)) is None and not principal.is_admin)
    ):
        raise AccessDenied
    conversation = await create_conversation(session, principal, project_id=project_id, title=f"◎ {title}")
    goal = Goal(
        user_id=uuid.UUID(principal.user_id),
        project_id=pid,
        conversation_id=conversation.id,
        title=title.strip()[:300],
        outcome=outcome.strip(),
        due_date=due_date,
        autonomy=autonomy.value,
        lang=lang,
        status="planning",
    )
    session.add(goal)
    await session.flush()
    goal.plan = await plan_goal(goal, project.name if project else None)
    goal.status = "proposed" if autonomy in (AutonomyMode.observe, AutonomyMode.suggest) else "active"
    await audit(
        session, actor_id=goal.user_id, action="goal.create", target_type="goal", target_id=str(goal.id), summary=goal.title
    )
    to_dispatch = await advance(session, goal) if goal.status == "active" else []
    return goal, to_dispatch


# --- Mission ----------------------------------------------------------------------------------------------


TASK_TO_MILESTONE = {
    TaskStatus.completed.value: "done",
    TaskStatus.failed.value: "blocked",
    TaskStatus.cancelled.value: "blocked",
    TaskStatus.waiting_user.value: "waiting",
    TaskStatus.paused.value: "working",
    TaskStatus.running.value: "working",
    TaskStatus.queued.value: "working",
    TaskStatus.scheduled.value: "working",
}


def _task_autonomy(goal: Goal) -> AutonomyMode:
    mode = AutonomyMode(goal.autonomy)
    return AutonomyMode.execute_with_approval if mode in (AutonomyMode.observe, AutonomyMode.suggest) else mode


async def _sync(session: AsyncSession, goal: Goal) -> list[dict[str, Any]]:
    items = milestones(goal)
    for m in items:
        if not m.get("task_id") or m.get("status") in ("done", "skipped"):
            continue
        task = await session.get(Task, uuid.UUID(m["task_id"]))
        if task is None:
            continue
        status = TASK_TO_MILESTONE.get(task.status, m["status"])
        if status != m["status"]:
            m["status"] = status
            if status in ("done", "blocked"):
                m["finished_at"] = (task.finished_at or utcnow()).isoformat()
            if status == "blocked":
                m["note"] = (task.error or "")[:300]
        if status == "done":
            m["artifact_ids"] = [str(s.artifact_id) for s in task.steps if s.artifact_id]
    return items


async def _launch(session: AsyncSession, goal: Goal, m: dict[str, Any]) -> str:
    user = await session.get(User, goal.user_id)
    conversation = await session.get(Conversation, goal.conversation_id) if goal.conversation_id else None
    assert user is not None and conversation is not None
    registry = get_skill_registry()
    lead = "Objectif" if goal.lang == "fr" else "Goal"
    text = (
        f"/{m['skill_id']} {m['title']} — {m['goal']}\n\n{lead} : {goal.title}."
        if goal.lang == "fr"
        else f"/{m['skill_id']} {m['title']} — {m['goal']}\n\n{lead}: {goal.title}."
    )
    if goal.outcome:
        text += f" {goal.outcome}"
    _, _, task = await submit(
        session,
        principal_for(user),
        conversation,
        ComposerInput(
            text=text,
            project_id=str(goal.project_id) if goal.project_id else None,
            skill_refs=[m["skill_id"]],
            autonomy=_task_autonomy(goal),
        ),
        {s.id for s in registry.all()},
    )
    task.origin = "goal"
    task.input = {**task.input, "goal_id": str(goal.id), "milestone_id": m["id"], "subject": goal.title}
    m.update(status="working", task_id=str(task.id), started_at=utcnow().isoformat())
    return str(task.id)


async def advance(session: AsyncSession, goal: Goal) -> list[str]:
    """Sync milestones with their tasks, then start the next step the autonomy allows. Returns task ids to dispatch."""
    items = await _sync(session, goal)
    to_dispatch: list[str] = []
    if goal.status == "active" and not any(m.get("status") in (*RUNNING, "blocked", "ready") for m in items):
        nxt = next((m for m in items if m.get("status") == "pending"), None)
        if nxt is None:
            goal.status, goal.completed_at = "completed", utcnow()
            await audit(
                session,
                actor_id=goal.user_id,
                action="goal.complete",
                target_type="goal",
                target_id=str(goal.id),
                summary=goal.title,
            )
        elif nxt["kind"] == "human":
            nxt["status"] = "waiting"  # the team's decision or action: NOVA asks in the Inbox
        elif AutonomyMode(goal.autonomy) == AutonomyMode.suggest:
            nxt["status"] = "ready"  # NOVA proposes the next step; the user starts it
        else:
            to_dispatch.append(await _launch(session, goal, nxt))
    _save(goal, items)
    return to_dispatch


def _find(items: list[dict[str, Any]], milestone_id: str) -> dict[str, Any]:
    m = next((m for m in items if m["id"] == milestone_id), None)
    if m is None:
        raise GoalError("not_found", "This milestone does not exist.")
    return m


async def act(session: AsyncSession, goal: Goal, action: str, milestone_id: str | None = None, note: str = "") -> list[str]:
    """User decisions on a goal or one of its milestones. Returns task ids to dispatch."""
    items = milestones(goal)
    to_dispatch: list[str] = []
    if action == "approve":  # accept NOVA's plan (suggest / observe) and start the mission
        if goal.status not in ("proposed", "paused"):
            raise GoalError("invalid_state", "This goal is not waiting for approval.")
        goal.status = "active"
        if goal.autonomy == AutonomyMode.observe.value:
            goal.autonomy = AutonomyMode.suggest.value  # approving an observed plan lets NOVA propose each step
    elif action == "pause":
        goal.status = "paused"
    elif action == "resume":
        goal.status = "active"
    elif action == "archive":
        goal.status = "archived"
    elif milestone_id:
        m = _find(items, milestone_id)
        if action == "start" and m["status"] in ("ready", "pending") and m["kind"] == "skill":
            to_dispatch.append(await _launch(session, goal, m))
            _save(goal, items)
            await audit(
                session,
                actor_id=goal.user_id,
                action="goal.start",
                target_type="goal",
                target_id=str(goal.id),
                summary=m["title"],
            )
            return to_dispatch
        if action == "done" and m["status"] in ("waiting", "ready", "pending", "blocked"):
            m.update(status="done", note=note[:500], finished_at=utcnow().isoformat())
        elif action == "skip":
            m.update(status="skipped", note=note[:500], finished_at=utcnow().isoformat())
        elif action == "retry" and m["status"] == "blocked":
            m.update(status="pending", task_id=None, note="")
        else:
            raise GoalError("invalid_state", "This action is not available for this milestone.")
    else:
        raise GoalError("invalid_action", "Unknown action.")
    _save(goal, items)
    await audit(
        session,
        actor_id=goal.user_id,
        action=f"goal.{action}",
        target_type="goal",
        target_id=str(goal.id),
        summary=milestone_id or goal.title,
    )
    to_dispatch += await advance(session, goal)
    return to_dispatch


async def advance_open_goals(
    session: AsyncSession, *, user_id: uuid.UUID | None = None, goal_id: uuid.UUID | None = None
) -> list[str]:
    query = select(Goal).where(Goal.status.in_(("active",)))
    if user_id:
        query = query.where(Goal.user_id == user_id)
    if goal_id:
        query = query.where(Goal.id == goal_id)
    to_dispatch: list[str] = []
    for goal in (await session.scalars(query.limit(200))).all():
        try:
            to_dispatch += await advance(session, goal)
        except Exception:  # one goal must never block the others
            log.exception("Goal %s could not advance", goal.id)
    return to_dispatch
