"""plan_execution / plan_edit / select_skills."""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from nova.agent import prompts
from nova.agent.deps import AgentDeps
from nova.agent.nodes.common import NodeFailure, deps, node, now_iso, plan_block, progress, set_phase, upsert
from nova.domain.enums import ExecutionOrigin, NovaPhase, StepStatus
from nova.domain.outputs import ExecutionPlan, ExecutionStep, MissingInput, PlanOutput
from nova.domain.permissions import AutonomyPolicy
from nova.domain.skills import SelectedSkill
from nova.domain.state import NovaState, StepOutput
from nova.skills.router import SkillRouter

EDIT_SKILL = "artifact-edit"


def _slug(text: str, index: int) -> str:
    base = "".join(ch if ch.isalnum() else "-" for ch in text.lower()).strip("-")[:30] or "step"
    return f"{index}-{base}"


@node("plan_execution")
async def plan_execution(state: NovaState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    d = deps(runtime)
    c = state.classification
    assert c is not None
    await set_phase(d, state, NovaPhase.planning, "Planning")
    await progress(d, state, "plan", "Planning the work", "running")

    router = SkillRouter(d.skills)
    candidates = router.candidates(
        f"{state.intent}\n{c.goal}",
        category=c.category,
        artifact_type=c.artifact_type,
        explicit=state.skill_refs,
        hinted=c.candidate_skill_ids,
        preferred_methods=state.preferences.get("preferred_methods"),
    )
    if not candidates:
        candidates = router.candidates(c.goal, hinted=c.candidate_skill_ids) or []
    if not candidates:
        raise NodeFailure("no_skill", "NOVA has no Skill for this request yet.")
    can_ask = state.origin == ExecutionOrigin.interactive
    max_steps = d.settings.max_workflow_steps

    explicit = [s for s in state.skill_refs if d.skills.has(s)]
    if explicit:  # "/prd" — the user chose; no model call needed
        plan_out = PlanOutput(
            objective=c.goal,
            steps=[{"id": _slug(s, i + 1), "title": d.skills.get(s).name, "skill_id": s} for i, s in enumerate(explicit)],
        )
        usage = state.usage
        if can_ask:
            plan_out.missing_inputs = _missing_required(state, [d.skills.get(s) for s in explicit])
    else:
        result = await d.llm.structured_output(
            prompts.plan_messages(state, [cand.skill for cand in candidates], can_ask=can_ask), PlanOutput
        )
        plan_out, usage = result.value, state.usage.add(result.usage)

    allowed = {cand.skill.id for cand in candidates}
    steps: list[ExecutionStep] = []
    for i, planned in enumerate(plan_out.steps):
        if planned.skill_id not in allowed or any(s.skill_id == planned.skill_id for s in steps):
            continue  # the model can only pick among routed candidates, once each
        skill = d.skills.get(planned.skill_id)
        steps.append(
            ExecutionStep(
                id=_slug(planned.title or skill.name, i + 1),
                title=planned.title or skill.name,
                skill_id=skill.id,
                skill_version=skill.version,
                rationale=planned.rationale,
            )
        )
        if len(steps) >= max_steps:
            break
    # The requested deliverable must be produced by its own Skill: the model may not replace it with
    # smaller Skills (e.g. "a PRD" planned as requirements + stories without the PRD itself).
    required = _required_skill(candidates, c.artifact_type)
    if required and all(s.skill_id != required.id for s in steps):
        steps.insert(
            0,
            ExecutionStep(
                id=_slug(required.name, 0),
                title=required.name,
                skill_id=required.id,
                skill_version=required.version,
                rationale="Produces the requested deliverable",
            ),
        )
        steps = steps[:max_steps]
    if not steps:
        best = candidates[0].skill
        steps = [ExecutionStep(id=_slug(best.name, 1), title=best.name, skill_id=best.id, skill_version=best.version)]

    chosen = [d.skills.get(s.skill_id) for s in steps if s.skill_id]
    declared = {(s.id, i.name) for s in chosen for i in s.inputs if i.required and i.ask}
    missing = [m for m in plan_out.missing_inputs if (m.skill_id, m.key) in declared or any(m.key == k for _, k in declared)]
    missing = [m for m in missing if m.key not in state.user_inputs][:3] if can_ask else []

    policy = AutonomyPolicy(mode=state.autonomy, allow_auto_external_writes=d.settings.policy_allow_auto_external_writes)
    needs_confirmation = state.origin == ExecutionOrigin.interactive and policy.confirm_workflow(len(steps)) and not explicit
    plan = ExecutionPlan(
        objective=plan_out.objective or c.goal,
        steps=steps,
        requires_user_input=bool(missing),
        missing_inputs=missing,
        assumptions=plan_out.assumptions,
        confirmed=not needs_confirmation,
    )
    plan.workflow_id = await d.store.save_plan(state.task_id, plan)
    new_state = state.model_copy(update={"plan": plan})
    if plan.confirmed:  # a proposed workflow is shown by confirm_workflow; the plan block follows confirmation
        await upsert(d, new_state, plan_block(new_state, d))
    await progress(
        d,
        state,
        "plan",
        "Planning the work",
        "completed",
        f"{len(steps)} step{'s' if len(steps) > 1 else ''}: " + " → ".join(s.title for s in steps),
    )
    return {
        "plan": plan,
        "selected_skills": [
            SelectedSkill(skill_id=s.skill_id or "", version=s.skill_version or "", step_id=s.id, reason=s.rationale)
            for s in steps
        ],
        "pending_questions": missing,
        "usage": usage,
    }


def _required_skill(candidates: list, artifact_type: str | None):
    """The Skill the user explicitly asked for: requested Artifact type, or a trigger/name match of the best candidate."""
    if artifact_type:
        for cand in candidates:
            if cand.skill.outputs.artifact_type == artifact_type and cand.skill.outputs.mode == "create":
                return cand.skill
    best = candidates[0] if candidates else None
    if best and any(r.startswith("trigger") or r == "name match" for r in best.reasons) and best.score >= 6:
        return best.skill
    return None


def _missing_required(state: NovaState, skills: list) -> list[MissingInput]:
    """Explicit Skill invocations: ask required inputs only when the request is too short to contain them."""
    if len(state.intent.split()) > 6:
        return []
    return [
        MissingInput(key=i.name, question=i.question or i.description, skill_id=s.id)
        for s in skills
        for i in s.inputs
        if i.required and i.ask and i.name not in state.user_inputs
    ]


@node("plan_edit")
async def plan_edit(state: NovaState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    """Conversational Artifact editing: one step, only the targeted sections."""
    d = deps(runtime)
    c = state.classification
    assert c is not None and c.target_artifact_id
    snapshot = await d.store.get_artifact(c.target_artifact_id, state.user_id)
    if snapshot is None:
        raise NodeFailure("artifact_not_found", "NOVA can't access this Artifact.")
    artifact_type = d.artifacts.get(snapshot.type)
    sections = c.target_sections or artifact_type.section_keys
    titles = ", ".join(artifact_type.section(k).title for k in sections if artifact_type.section(k))  # type: ignore[union-attr]
    skill = d.skills.get(EDIT_SKILL)
    step = ExecutionStep(
        id="1-edit",
        title=f"Update {titles}" if c.target_sections else f"Update {snapshot.title}",
        skill_id=skill.id,
        skill_version=skill.version,
    )
    plan = ExecutionPlan(objective=c.goal, steps=[step], confirmed=True)
    plan.workflow_id = await d.store.save_plan(state.task_id, plan)
    new_state = state.model_copy(update={"plan": plan})
    await upsert(d, new_state, plan_block(new_state, d))
    output = StepOutput(
        step_id=step.id,
        skill_id=skill.id,
        skill_version=skill.version,
        artifact_type=snapshot.type,
        target_artifact_id=snapshot.artifact_id,
        edit_sections=sections,
    )
    return {
        "plan": plan,
        "selected_skills": [SelectedSkill(skill_id=skill.id, version=skill.version, step_id=step.id)],
        "step_outputs": {**state.step_outputs, step.id: output},
    }


@node("select_skills")
async def select_skills(state: NovaState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    """Resolve the next plan step to a Skill version and its target Artifact."""
    d = deps(runtime)
    plan = state.plan.model_copy(deep=True) if state.plan else None
    if plan is None:
        raise NodeFailure("no_plan", "No plan to execute.")
    step = plan.next_pending()
    if step is None:
        return {"current_step": None}
    if step.id in state.step_outputs:
        return {"current_step": step.id}
    skill = d.skills.get(step.skill_id or "")
    if skill.version != step.skill_version:
        raise NodeFailure("skill_version_changed", f"Skill {skill.id} changed during execution; retry the task.")
    target = None
    if skill.outputs.mode == "update":
        # update Skills enrich an Artifact of their type created earlier in this run, or the one in view
        earlier = [o for o in state.step_outputs.values() if o.artifact_type == skill.outputs.artifact_type and o.artifact_id]
        if earlier:
            target = earlier[-1].artifact_id
        elif state.active_artifact_id:
            snap = await d.store.get_artifact(state.active_artifact_id, state.user_id)
            target = snap.artifact_id if snap and snap.type == skill.outputs.artifact_type else None
    output = StepOutput(
        step_id=step.id,
        skill_id=skill.id,
        skill_version=skill.version,
        artifact_type=skill.outputs.artifact_type,
        target_artifact_id=target,
    )
    for s in plan.steps:
        if s.id == step.id:
            s.status = StepStatus.running
            s.started_at = s.started_at or now_iso()
    await d.store.update_step(state.task_id, step.id, StepStatus.running)
    new_state = state.model_copy(update={"plan": plan})
    await upsert(d, new_state, plan_block(new_state, d))
    await set_phase(d, state, NovaPhase.executing, f"Running {skill.name}")
    return {
        "plan": plan,
        "current_step": step.id,
        "step_outputs": {**state.step_outputs, step.id: output},
        "phase": NovaPhase.executing,
    }
