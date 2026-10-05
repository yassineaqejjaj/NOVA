"""finalize / emit_forge_trace."""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime
from typing import Any

from langgraph.runtime import Runtime
from opentelemetry import trace

from nova.agent.deps import AgentDeps
from nova.agent.nodes.common import deps, node, now_iso, plan_block, set_phase, upsert
from nova.artifacts.render import render_markdown
from nova.domain.blocks import error_block, text_block
from nova.domain.enums import ExecutionOrigin, IntentKind, NovaPhase, StepStatus
from nova.domain.evaluation import ExecutionRecord, SkillUse
from nova.domain.state import NovaState

log = logging.getLogger(__name__)

FRIENDLY_ERRORS = {
    "model_error": "The model could not produce a valid result.",
    "no_skill": "NOVA has no Skill for this request yet.",
    "artifact_not_found": "NOVA can't access this Artifact.",
    "empty_output": "The model returned no usable content.",
}


@node("finalize")
async def finalize(state: NovaState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    d = deps(runtime)
    if state.status == "failed":
        error = state.errors[-1] if state.errors else None
        message = error.message if error else "Something went wrong."
        kept = f" {len(state.artifacts)} Artifact(s) produced before the failure were kept." if state.artifacts else ""
        await upsert(
            d, state, error_block("NOVA couldn't finish this task", message + kept, [{"label": "Retry", "action": "retry"}])
        )
        if state.plan and state.current_step:
            await d.store.update_step(state.task_id, state.current_step, StepStatus.failed, detail=message[:200])
            for s in state.plan.steps:
                if s.id == state.current_step:
                    s.status, s.finished_at = StepStatus.failed, now_iso()
            await upsert(d, state, plan_block(state, d))
        await set_phase(d, state, NovaPhase.failed, "Failed")
        return {"phase": NovaPhase.failed}
    if state.status == "cancelled":
        await upsert(d, state, text_block("Workflow cancelled. Nothing was created."))
        await set_phase(d, state, NovaPhase.completed, "Cancelled")
        return {"phase": NovaPhase.completed}

    c = state.classification
    if c and c.kind in (IntentKind.run_workflow, IntentKind.edit_artifact) and state.artifacts:
        lines = []
        for ref in state.artifacts:
            if ref.created:
                lines.append(f"Created **{ref.title}** (v{ref.version}).")
            elif ref.changed_sections:
                lines.append(f"Updated **{ref.title}** (v{ref.version}).")
            else:
                lines.append(f"No change was needed to **{ref.title}** (still v{ref.version}).")
        summaries = [s for out in state.step_outputs.values() for s in out.summaries[:1]]
        if summaries:
            lines.append(" ".join(summaries)[:700])
        suggestions = []
        planned = {s.skill_id for s in state.plan.steps} if state.plan else set()
        last = list(state.step_outputs.values())[-1] if state.step_outputs else None
        if last and d.skills.has(last.skill_id):
            for follow in d.skills.get(last.skill_id).composes_with:
                if follow not in planned and d.skills.has(follow):
                    skill = d.skills.get(follow)
                    suggestions.append({"skill_id": skill.id, "label": skill.name})
        block = text_block("\n\n".join(lines))
        block.data["suggestions"] = suggestions[:3]
        await upsert(d, state, block)
    elif c and c.kind in (IntentKind.run_workflow, IntentKind.edit_artifact) and not state.artifacts:
        await upsert(d, state, text_block("No Artifact was changed."))
    await set_phase(d, state, NovaPhase.completed, "Completed")
    return {"status": "completed", "phase": NovaPhase.completed}


def should_capture(policy: str, rate: float) -> bool:
    return policy == "all" or (policy == "sampled" and random.random() < rate)


async def build_execution_record(state: NovaState, d: AgentDeps) -> ExecutionRecord:
    outputs = []
    for ref in state.artifacts:
        snapshot = await d.store.get_artifact(ref.artifact_id, state.user_id)
        if snapshot:
            outputs.append(render_markdown(snapshot.content, d.artifacts.get(snapshot.type)))
    if state.answer:
        outputs.append(state.answer.text)
    return ExecutionRecord(
        task_id=state.task_id,
        trace_id=state.trace_id,
        user_intent=state.intent,
        origin=state.origin.value,
        agent_version=d.settings.version,
        model=state.model,
        workflow=[s.skill_id for s in state.plan.steps if s.skill_id] if state.plan else [],
        skills=[
            SkillUse(
                skill_id=o.skill_id,
                version=o.skill_version,
                step_id=o.step_id,
                status="completed" if o.artifact_id else "incomplete",
                duration_ms=o.duration_ms,
            )
            for o in state.step_outputs.values()
        ],
        context_retrieval_ids=[state.context_retrieval_id] if state.context_retrieval_id else [],
        context_documents=[
            {"id": i.citation, "title": i.title, "content": i.excerpt, "source": i.source_system} for i in state.context_items
        ],
        context_max_classification=max((i.classification for i in state.context_items), default=0),
        tools=sorted({r.tool for o in state.step_outputs.values() for r in o.tool_results}),
        artifact_ids=[a.artifact_id for a in state.artifacts],
        artifact_type=state.artifacts[-1].type if state.artifacts else None,
        output_markdown="\n\n".join(outputs),
        usage=state.usage,
        status=state.status,
        errors=[e.message for e in state.errors],
        finished_at=datetime.now(UTC),
    )


@node("emit_forge_trace")
async def emit_forge_trace(state: NovaState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    """Record execution attributes on the trace; capture into FORGE according to policy.

    FORGE-initiated runs are already in FORGE (the protocol response carries the events).
    """
    d = deps(runtime)
    span = trace.get_current_span()
    span.set_attribute("nova.status", state.status)
    span.set_attribute("nova.artifacts", [a.artifact_id for a in state.artifacts])
    span.set_attribute("gen_ai.usage.input_tokens", state.usage.input_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", state.usage.output_tokens)
    if state.origin == ExecutionOrigin.forge_protocol or d.evaluation is None:
        return {}
    if state.status != "completed" or not should_capture(d.settings.forge_capture_policy, d.settings.forge_capture_sample_rate):
        return {}
    try:
        record = await build_execution_record(state, d)
        reference = await d.evaluation.capture(record)
        if reference is not None:
            await d.store.save_evaluation_reference(state.task_id, reference)
    except Exception:
        log.warning("FORGE capture failed for task %s", state.task_id, exc_info=True)
    return {}
