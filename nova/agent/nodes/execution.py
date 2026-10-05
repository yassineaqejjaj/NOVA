"""execute_skill / execute_tools / generate_artifact."""

from __future__ import annotations

import re
from typing import Any

from langgraph.runtime import Runtime
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from nova.agent import prompts
from nova.agent.deps import AgentDeps
from nova.agent.nodes.common import NodeFailure, deps, node, now_iso, plan_block, progress, set_phase, upsert
from nova.agent.nodes.context import relabel, scan
from nova.agent.nodes.interaction import new_approval
from nova.agent.nodes.planning import EDIT_SKILL
from nova.agent.tools.registry import ToolContext, ToolDenied
from nova.artifacts.registry import NormalizationReport
from nova.artifacts.render import render_section
from nova.domain.artifacts import ArtifactReference, Citation, apply_section_updates, empty_content
from nova.domain.blocks import Block
from nova.domain.context import ContextBundle
from nova.domain.enums import BlockType, NovaPhase, SectionKind, StepStatus
from nova.domain.outputs import ToolRequest, ToolResult
from nova.domain.permissions import AutonomyPolicy
from nova.domain.skills import SkillStep
from nova.domain.state import NovaState


class RawStepOutput(BaseModel):
    """Envelope of a Skill sub-step output; ``sections`` is validated against the dynamic JSON Schema."""

    summary: str = ""
    sections: dict[str, Any] = Field(default_factory=dict)
    tool_requests: list[ToolRequest] = Field(default_factory=list)


def policy_for(state: NovaState, d: AgentDeps) -> AutonomyPolicy:
    return AutonomyPolicy(mode=state.autonomy, allow_auto_external_writes=d.settings.policy_allow_auto_external_writes)


def citation_index(state: NovaState) -> dict[str, Citation]:
    return {i.citation: Citation(label=i.citation, ref=i.reference_id, title=i.title) for i in state.context_items}


def _previous_outputs(state: NovaState, d: AgentDeps, current: str) -> list[str]:
    result = []
    for step_id, out in state.step_outputs.items():
        if step_id == current or not out.sections:
            continue
        artifact_type = d.artifacts.get(out.artifact_type)
        lines = [f"### {artifact_type.name} (from step '{step_id}')"]
        for key, section in out.sections.items():
            title = artifact_type.section(key).title if artifact_type.section(key) else key  # type: ignore[union-attr]
            lines += [f"#### {title}", *render_section(section)]
        result.append("\n".join(lines))
    return result


def _count(sections: dict, keys: list[str]) -> str:
    items = sum(len(sections[k].items) for k in keys if k in sections and sections[k].kind == SectionKind.items)
    return f"{items} item{'s' if items != 1 else ''}" if items else f"{len(keys)} section{'s' if len(keys) != 1 else ''}"


@node("execute_skill")
async def execute_skill(state: NovaState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    d = deps(runtime)
    step_id = state.current_step
    if not step_id or step_id not in state.step_outputs:
        raise NodeFailure("no_step", "No step to execute.")
    out = state.step_outputs[step_id].model_copy(deep=True)
    skill = d.skills.get(out.skill_id)
    artifact_type = d.artifacts.get(out.artifact_type)
    existing = await d.store.get_artifact(out.target_artifact_id, state.user_id) if out.target_artifact_id else None
    if out.target_artifact_id and existing is None:
        raise NodeFailure("artifact_not_found", "NOVA can't access the Artifact to update.")

    if out.skill_execution_id is None:
        out.skill_execution_id = await d.store.start_skill_execution(
            task_id=state.task_id, step_id=step_id, skill=skill, inputs={"intent": state.intent, **state.user_inputs}
        )

    is_edit = skill.id == EDIT_SKILL
    if is_edit:
        fills = out.edit_sections
        sub = SkillStep(
            id="edit",
            title=f"Updating {', '.join(artifact_type.section(k).title for k in fills)}",  # type: ignore[union-attr]
            instruction=skill.steps[0].instruction,
            fills=fills,
        )
    else:
        sub = skill.steps[out.substep_index]
        fills = sub.fills
    tools_allowed = skill.tools if state.tool_iterations < d.settings.max_tool_iterations else []

    schema = d.artifacts.output_schema(artifact_type, fills, with_tools=bool(tools_allowed))
    if is_edit:
        schema["properties"]["sections"]["required"] = []  # return only the sections that change

    progress_key = f"{step_id}:{sub.id}"
    await progress(d, state, progress_key, sub.title, "running")
    messages = prompts.skill_step_messages(
        state,
        skill,
        sub,
        artifact_type,
        fills=fills,
        produced=out.sections,
        existing=existing,
        previous_outputs=_previous_outputs(state, d, step_id),
        tool_results=out.tool_results,
        tools_allowed=tools_allowed,
        edit_instruction=state.intent if is_edit else None,
    )
    result = await d.llm.structured_output(messages, RawStepOutput, json_schema=schema)
    raw = result.value
    out.usage = out.usage.add(result.usage)
    out.duration_ms += result.latency_ms
    usage = state.usage.add(result.usage)

    if raw.tool_requests and tools_allowed:
        await progress(
            d, state, progress_key, sub.title, "running", "Using tools: " + ", ".join(r.tool for r in raw.tool_requests)
        )
        return {
            "step_outputs": {**state.step_outputs, step_id: out},
            "pending_tool_requests": raw.tool_requests[:3],
            "usage": usage,
            "model": result.model,
        }

    report = NormalizationReport()
    id_scope = set(out.id_scope)
    sections = d.artifacts.normalize_sections(
        artifact_type,
        raw.sections,
        allowed_keys=fills,
        citation_index=citation_index(state),
        existing=existing.content if existing else None,
        report=report,
        id_scope=id_scope,
    )
    if not is_edit and not any(not s.is_empty() for s in sections.values()):
        raise NodeFailure("empty_output", f"{skill.name}: the model returned no content for '{sub.title}'.")
    out.sections = {**out.sections, **sections}
    out.id_scope = sorted(id_scope)
    if raw.summary:
        out.summaries.append(raw.summary.strip())
    out.dropped_citations += len(report.dropped_citations)
    out.tool_results = []
    out.substep_index += 1
    out.done = is_edit or out.substep_index >= len(skill.steps)
    detail = _count(out.sections, fills) if sections else "No change needed"
    if report.dropped_citations:
        detail += f" · {len(report.dropped_citations)} unverifiable citation(s) removed"
    await progress(d, state, progress_key, sub.title, "completed", detail)
    return {
        "step_outputs": {**state.step_outputs, step_id: out},
        "pending_tool_requests": [],
        "tool_iterations": 0,
        "usage": usage,
        "model": result.model,
    }


@node("execute_tools")
async def execute_tools(state: NovaState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    d = deps(runtime)
    step_id = state.current_step or ""
    out = state.step_outputs[step_id].model_copy(deep=True)
    skill = d.skills.get(out.skill_id)
    policy = policy_for(state, d)

    # 1) Authorize everything first; collect external writes needing approval (no side effect yet).
    authorized: list[tuple[ToolRequest, Any]] = []
    results: list[ToolResult] = []
    needs_approval = []
    for request in state.pending_tool_requests:
        try:
            tool = d.tools.authorize(request, allowed=skill.tools, permissions=d.permissions)
        except ToolDenied as exc:
            results.append(ToolResult(tool=request.tool, status="denied", error=str(exc)))
            continue
        authorized.append((request, tool))
        if tool.external_write and policy.approve_external_write():
            needs_approval.append(request)

    approved_by = None
    if needs_approval:
        approval = new_approval(
            "external_write",
            "Approve external change",
            "; ".join(f"{r.tool}: {r.reason or r.arguments}" for r in needs_approval)[:500],
            tool_request=needs_approval[0],
        )
        block = Block(
            key=f"approval-{approval.id}", type=BlockType.decision, data={**approval.model_dump(mode="json"), "status": "pending"}
        )
        await upsert(d, state, block)
        await set_phase(d, state, NovaPhase.waiting_user, "Waiting for your approval")
        decision = interrupt({"kind": "approval", "approval_id": approval.id}) or {}
        accepted = decision.get("action") == "approve"
        await upsert(
            d, state, block.model_copy(update={"data": {**block.data, "status": "approved" if accepted else "rejected"}})
        )
        await set_phase(d, state, NovaPhase.executing, "Executing")
        if accepted:
            approved_by = state.user_id
        else:
            rejected = {id(r) for r in needs_approval}
            results += [
                ToolResult(tool=r.tool, status="denied", error="Rejected by the user") for r, _ in authorized if id(r) in rejected
            ]
            authorized = [(r, t) for r, t in authorized if id(r) not in rejected]

    # 2) Execute.
    context_items = list(state.context_items)
    for request, tool in authorized:
        await upsert(
            d,
            state,
            Block(
                key=f"tool-{step_id}-{tool.name}",
                type=BlockType.tool_execution,
                data={"tool": tool.name, "status": "running", "summary": request.reason},
            ),
        )
        result, ms = await d.tools.execute(tool, request, ToolContext(state=state, deps=d, skill_id=skill.id))
        if tool.name == "retrieve_orbit_context" and result.status == "ok":
            new_items = scan(relabel([i for i in _items_from(result.output)], len(context_items) + 1))
            if new_items:
                bundle = ContextBundle(
                    retrieval_id=result.output.get("retrieval_id"), project_slug=state.project_slug, items=new_items
                )
                ref = await d.store.record_context(
                    task_id=state.task_id,
                    user_id=state.user_id,
                    conversation_id=state.conversation_id,
                    query=str(request.arguments.get("query", "")),
                    bundle=bundle,
                )
                context_items += [i.model_copy(update={"reference_id": ref}) for i in new_items]
            result = result.model_copy(update={"output": {"added": [{"label": i.citation, "title": i.title} for i in new_items]}})
        results.append(result)
        if tool.audit:
            await d.store.record_tool_execution(
                task_id=state.task_id,
                skill_execution_id=out.skill_execution_id,
                request=request,
                result=result,
                duration_ms=ms,
                approved_by=approved_by,
            )
        await upsert(
            d,
            state,
            Block(
                key=f"tool-{step_id}-{tool.name}",
                type=BlockType.tool_execution,
                data={
                    "tool": tool.name,
                    "status": result.status,
                    "summary": request.reason,
                    "error": result.error,
                    "duration_ms": round(ms),
                },
            ),
        )
    out.tool_results += results
    return {
        "step_outputs": {**state.step_outputs, step_id: out},
        "pending_tool_requests": [],
        "tool_iterations": state.tool_iterations + 1,
        "context_items": context_items,
    }


def _items_from(output: Any) -> list:
    from nova.domain.context import ContextItem

    return [ContextItem.model_validate(i) for i in (output or {}).get("items", [])]


_SLASH = re.compile(r"(?:^|\s)/[a-z][a-z0-9-]+\s*")


_LEAD = re.compile(
    r"^(?:please\s+)?(?:help me\s+)?(?:to\s+)?(?:create|write|draft|prepare|generate|build|make|produce|define|plan|turn|answer)\b\s*"
    r"(?:(?:a|an|the|our|my)\s+)?",
    re.IGNORECASE,
)
_DELIVERABLE = re.compile(
    r"^(?:prd|prfaq|backlog|sprint plan|release plan|roadmap|user stories|stories|product requirements document|"
    r"decision record|vision|strategy|okrs?|persona|journey|experiment|brief|update|summary)\b\s*(?:for|of|about|on)?\s*",
    re.IGNORECASE,
)


def _title(state: NovaState, type_name: str) -> str:
    """'Create a PRD for QR-code desk check-in in Atlas' → 'QR-code desk check-in in Atlas – Product Requirements Document'."""
    objective = _SLASH.sub(" ", (state.plan.objective if state.plan else state.intent)).strip().rstrip(".?!")
    subject = _DELIVERABLE.sub("", _LEAD.sub("", objective)).strip(" ,:-–")
    subject = re.sub(r"^(?:the\s+)?user'?s?\s+question\s+(?:about|on)\s+(?:the\s+)?", "", subject, flags=re.IGNORECASE)
    subject = re.sub(r"\s+into\s+(?:a|an|the)?\s*\w+(?:\s+\w+)?$", "", subject, flags=re.IGNORECASE)
    subject = re.sub(r"^(?:a|an|the)\s+", "", subject, flags=re.IGNORECASE)
    subject = re.split(r",\s*(?:so that|in order to|to ensure)\b", subject, maxsplit=1)[0].strip()
    if not subject or len(subject) > 70:
        return type_name
    return f"{subject[0].upper()}{subject[1:]} – {type_name}"


@node("generate_artifact")
async def generate_artifact(state: NovaState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    d = deps(runtime)
    step_id = state.current_step or ""
    out = state.step_outputs[step_id].model_copy(deep=True)
    artifact_type = d.artifacts.get(out.artifact_type)
    existing = await d.store.get_artifact(out.target_artifact_id, state.user_id) if out.target_artifact_id else None
    base = existing.content if existing else empty_content(artifact_type, _title(state, artifact_type.name))
    content, changed = apply_section_updates(base, out.sections, artifact_type)
    context_classification = max((i.classification for i in state.context_items), default=0)
    classification = max(context_classification, existing.classification if existing else 0)
    summary = " ".join(out.summaries)[:600] or f"{artifact_type.name} updated"
    policy = policy_for(state, d)
    plan = state.plan.model_copy(deep=True) if state.plan else None
    updates: dict[str, Any] = {}

    if existing and not changed:
        artifact_id, version, proposed = existing.artifact_id, existing.version, False
        detail = "No changes were needed"
    else:
        proposed = policy.approve_artifact_changes(editing_existing=existing is not None)
        artifact_id, version = await d.store.save_artifact(
            task_id=state.task_id,
            user_id=state.user_id,
            artifact_id=existing.artifact_id if existing else None,
            project_id=state.project_id,
            conversation_id=state.conversation_id,
            content=content,
            changed_sections=changed,
            skill_execution_id=out.skill_execution_id,
            summary=summary,
            classification=classification,
            proposed=proposed,
        )
        detail = f"{'Proposed' if proposed else 'Saved'} v{version}"
    out.artifact_id, out.artifact_version = artifact_id, version
    await d.store.finish_skill_execution(
        out.skill_execution_id or "",
        status="completed",
        output={
            "artifact_id": artifact_id,
            "version": version,
            "changed_sections": changed,
            "summary": summary,
            "dropped_citations": out.dropped_citations,
        },
        usage=out.usage,
        model=state.model,
        duration_ms=out.duration_ms,
    )
    if plan:
        for s in plan.steps:
            if s.id == step_id:
                s.status, s.artifact_id, s.detail, s.finished_at = StepStatus.completed, artifact_id, detail, now_iso()
    await d.store.update_step(state.task_id, step_id, StepStatus.completed, detail=detail, artifact_id=artifact_id)

    reference = ArtifactReference(
        artifact_id=artifact_id,
        type=artifact_type.type,
        title=content.title,
        version=version,
        changed_sections=changed,
        created=existing is None,
    )
    titles = [artifact_type.section(k).title for k in changed if artifact_type.section(k)]  # type: ignore[union-attr]
    await upsert(
        d,
        state,
        Block(
            key=f"artifact-{artifact_id}",
            type=BlockType.artifact,
            data={
                **reference.model_dump(mode="json"),
                "type_name": artifact_type.name,
                "icon": artifact_type.icon,
                "changed_titles": titles,
                "summary": summary,
                "status": "proposed" if proposed else "current",
                "classification": classification,
            },
        ),
    )
    new_state = state.model_copy(update={"plan": plan})
    if plan:
        await upsert(d, new_state, plan_block(new_state, d))

    artifacts = [a for a in state.artifacts if a.artifact_id != artifact_id] + [reference]
    updates.update(plan=plan, artifacts=artifacts, step_outputs={**state.step_outputs, step_id: out}, current_step=None)
    if proposed:
        updates["approval"] = new_approval(
            "apply_artifact_changes",
            f"Apply changes to {content.title}",
            f"NOVA proposes version {version} ({', '.join(titles) or 'no section'}). Review and approve to make it current.",
            artifact_id=artifact_id,
            proposed_version=version,
        )
        updates["requires_approval"] = True
    return updates
