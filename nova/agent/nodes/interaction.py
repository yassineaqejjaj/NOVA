"""Human-in-the-loop nodes: questions, workflow confirmation, approvals (LangGraph ``interrupt``).

Each node does nothing irreversible before ``interrupt()``: on resume the node re-runs from the top
and ``interrupt()`` returns the user's answer.
"""

from __future__ import annotations

import uuid
from typing import Any

from langgraph.runtime import Runtime
from langgraph.types import interrupt

from nova.agent.deps import AgentDeps
from nova.agent.nodes.common import deps, node, plan_block, set_phase, upsert
from nova.domain.blocks import Block
from nova.domain.enums import BlockType, NovaPhase, StepStatus
from nova.domain.outputs import ExecutionStep
from nova.domain.state import ApprovalRequest, NovaState


@node("request_user_input")
async def request_user_input(state: NovaState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    d = deps(runtime)
    questions = [q.model_dump() for q in state.pending_questions]
    block = Block(key="questions", type=BlockType.question, data={"questions": questions, "answered": False})
    await upsert(d, state, block)
    await set_phase(d, state, NovaPhase.waiting_user, "Waiting for your answers")
    answers = interrupt({"kind": "questions", "questions": questions})
    answers = {str(k): str(v).strip() for k, v in (answers or {}).items() if str(v).strip()}
    # Questions are asked once: unanswered ones are recorded so NOVA proceeds with stated assumptions.
    answers = {**{q["key"]: "(not provided — make a reasonable assumption and state it)" for q in questions}, **answers}
    await upsert(d, state, block.model_copy(update={"data": {"questions": questions, "answered": True, "answers": answers}}))
    await set_phase(d, state, NovaPhase.planning, "Planning")
    return {"user_inputs": {**state.user_inputs, **answers}, "pending_questions": [], "phase": NovaPhase.planning}


@node("confirm_workflow")
async def confirm_workflow(state: NovaState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    """Show the proposed workflow; the user can run it, edit it (remove / reorder / add Skills) or cancel."""
    d = deps(runtime)
    assert state.plan is not None
    block = Block(
        key="workflow",
        type=BlockType.workflow,
        data={
            "workflow_id": state.plan.workflow_id,
            "objective": state.plan.objective,
            "status": "proposed",
            "steps": [{"id": s.id, "title": s.title, "skill_id": s.skill_id, "rationale": s.rationale} for s in state.plan.steps],
            "assumptions": state.plan.assumptions,
        },
    )
    await upsert(d, state, block)
    await set_phase(d, state, NovaPhase.waiting_user, "Waiting for you to confirm the workflow")
    decision = interrupt({"kind": "confirm_workflow", "workflow_id": state.plan.workflow_id}) or {}

    if decision.get("action") == "cancel":
        await upsert(d, state, block.model_copy(update={"data": {**block.data, "status": "cancelled"}}))
        return {"status": "cancelled", "phase": NovaPhase.completed}

    plan = state.plan.model_copy(deep=True)
    edited = decision.get("skill_ids")
    if isinstance(edited, list) and edited:
        steps: list[ExecutionStep] = []
        for i, skill_id in enumerate(dict.fromkeys(str(s) for s in edited)):
            if not d.skills.has(skill_id) or d.skills.get(skill_id).system:
                continue
            skill = d.skills.get(skill_id)
            previous = next((s for s in plan.steps if s.skill_id == skill_id), None)
            steps.append(
                ExecutionStep(
                    id=previous.id if previous else f"{i + 1}-{skill_id}",
                    title=previous.title if previous else skill.name,
                    skill_id=skill_id,
                    skill_version=skill.version,
                )
            )
        if steps:
            plan.steps = steps
            plan.workflow_id = await d.store.save_plan(state.task_id, plan)
    plan.confirmed = True
    for s in plan.steps:
        s.status = StepStatus.pending
    new_state = state.model_copy(update={"plan": plan})
    await upsert(
        d,
        new_state,
        block.model_copy(
            update={
                "data": {
                    **block.data,
                    "status": "confirmed",
                    "steps": [{"id": s.id, "title": s.title, "skill_id": s.skill_id} for s in plan.steps],
                }
            }
        ),
    )
    await upsert(d, new_state, plan_block(new_state, d))
    return {"plan": plan, "phase": NovaPhase.executing}


@node("request_approval")
async def request_approval(state: NovaState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    """Approval of proposed Artifact changes (execute_with_approval) — external writes are handled in execute_tools."""
    d = deps(runtime)
    approval = state.approval
    assert approval is not None
    block = Block(
        key=f"approval-{approval.id}", type=BlockType.decision, data={**approval.model_dump(mode="json"), "status": "pending"}
    )
    await upsert(d, state, block)
    await set_phase(d, state, NovaPhase.waiting_user, "Waiting for your approval")
    decision = interrupt({"kind": "approval", "approval_id": approval.id}) or {}
    approved = decision.get("action") == "approve"
    if approval.artifact_id and approval.proposed_version:
        if approved:
            await d.store.promote_proposed_version(approval.artifact_id, approval.proposed_version, state.user_id)
        else:
            await d.store.discard_proposed_version(approval.artifact_id, approval.proposed_version, state.user_id)
    await upsert(d, state, block.model_copy(update={"data": {**block.data, "status": "approved" if approved else "rejected"}}))
    artifacts = state.artifacts if approved else [a for a in state.artifacts if a.artifact_id != approval.artifact_id]
    return {
        "approval": None,
        "requires_approval": False,
        "approval_decision": "approved" if approved else "rejected",
        "artifacts": artifacts,
        "phase": NovaPhase.executing,
    }


def new_approval(action: str, title: str, description: str, **kwargs: Any) -> ApprovalRequest:
    return ApprovalRequest(id=uuid.uuid4().hex[:12], action=action, title=title, description=description, **kwargs)  # type: ignore[arg-type]
