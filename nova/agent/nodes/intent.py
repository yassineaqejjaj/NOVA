"""understand_intent — what is the user trying to achieve?"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from nova.agent import prompts
from nova.agent.deps import AgentDeps
from nova.agent.nodes.common import deps, node, progress, set_phase
from nova.domain.enums import ExecutionOrigin, IntentKind, NovaPhase
from nova.domain.outputs import IntentClassification
from nova.domain.state import NovaState


@node("understand_intent")
async def understand_intent(state: NovaState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    d = deps(runtime)
    await set_phase(d, state, NovaPhase.planning, "Understanding your request")
    await progress(d, state, "intent", "Understanding your request", "running")

    if state.edit_target:  # "Regenerate this section": the target is explicit, no model call needed
        c = IntentClassification(
            kind=IntentKind.edit_artifact,
            goal=state.intent[:300],
            target_artifact_id=state.edit_target.get("artifact_id"),
            target_sections=list(state.edit_target.get("sections") or []),
            needs_context=True,
            context_query=state.intent[:2000],
        )
        await progress(d, state, "intent", "Understanding your request", "completed", c.goal[:160])
        return {"classification": c, "phase": NovaPhase.planning}

    candidates = d.skills.all(include_system=False)
    ref_ids = list(dict.fromkeys([*([state.active_artifact_id] if state.active_artifact_id else []), *state.artifact_refs]))
    outlines = await d.store.list_artifact_outlines(state.user_id, project_id=state.project_id, ids=ref_ids or None, limit=8)
    if ref_ids:
        outlines += [
            o
            for o in await d.store.list_artifact_outlines(state.user_id, project_id=state.project_id, limit=5)
            if o.artifact_id not in ref_ids
        ]

    result = await d.llm.structured_output(
        prompts.intent_messages(state, candidates, outlines, sorted(d.artifacts.types)), IntentClassification
    )
    c = result.value

    # Validate everything the model referenced (it cannot invent artifacts, sections or skills).
    known = {o.artifact_id: o for o in outlines}
    if c.target_artifact_id not in known:
        c.target_artifact_id = (
            state.active_artifact_id if c.kind in (IntentKind.edit_artifact, IntentKind.explain_provenance) else None
        )
    outline = known.get(c.target_artifact_id or "")
    if outline:
        c.target_sections = [s for s in c.target_sections if s in outline.sections]
        if c.target_item_id and all(i["id"] != c.target_item_id for i in outline.items):
            c.target_item_id = None
    else:
        c.target_sections, c.target_item_id = [], None
        if c.kind in (IntentKind.edit_artifact, IntentKind.explain_provenance):
            c.kind = IntentKind.question  # nothing to edit/explain: answer instead of guessing
    c.candidate_skill_ids = [s for s in c.candidate_skill_ids if d.skills.has(s) and not d.skills.get(s).system]
    if c.artifact_type and c.artifact_type not in d.artifacts.types:
        c.artifact_type = None
    if state.skill_refs and c.kind in (IntentKind.question, IntentKind.smalltalk):
        c.kind = IntentKind.run_workflow  # an explicit /skill reference means "run it"
    if state.origin == ExecutionOrigin.forge_protocol and c.kind != IntentKind.run_workflow:
        c.kind = IntentKind.run_workflow

    await progress(d, state, "intent", "Understanding your request", "completed", c.goal[:160])
    return {
        "classification": c,
        "usage": state.usage.add(result.usage),
        "model": result.model,
        "phase": NovaPhase.planning,
    }
