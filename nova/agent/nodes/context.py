"""retrieve_orbit_context — governed context from ORBIT (ORBIT knows; NOVA only references)."""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from nova.agent.deps import AgentDeps
from nova.agent.nodes.common import deps, node, progress, set_phase, upsert
from nova.domain.blocks import Block, warning_block
from nova.domain.context import ContextBundle, ContextError, ContextItem, ContextQuery
from nova.domain.enums import CLASSIFICATION_LABELS, BlockType, ExecutionOrigin, IntentKind, NovaPhase
from nova.domain.state import ContextIssue, NovaState
from nova.domain.trust import detect_injection

PURPOSE_BY_CATEGORY = {
    "strategy": "general",
    "discovery": "research",
    "prioritization": "analysis",
    "definition": "specification",
    "delivery": "engineering",
    "analysis": "analysis",
    "communication": "general",
    "artifact": "general",
}

ERROR_COPY = {
    "forbidden": ("NOVA couldn't access this project's context", "ORBIT returned insufficient permissions."),
    "not_found": ("NOVA couldn't find this project in ORBIT", "The project does not exist or you are not a member."),
    "unauthorized": ("Your ORBIT session has expired", "Reconnect ORBIT to let NOVA use your project context."),
    "not_linked": ("ORBIT is not connected", "Connect your ORBIT account so NOVA can use your project context."),
    "unavailable": ("ORBIT is unavailable", "NOVA continued without project context."),
    "invalid": ("ORBIT rejected the context request", "NOVA continued without project context."),
}
ERROR_ACTIONS = {
    "forbidden": [
        {"label": "Request access", "action": "request_access"},
        {"label": "Choose another source", "action": "choose_source"},
        {"label": "Retry", "action": "retry"},
    ],
    "not_found": [{"label": "Choose another source", "action": "choose_source"}, {"label": "Retry", "action": "retry"}],
    "unauthorized": [{"label": "Reconnect ORBIT", "action": "link_orbit"}, {"label": "Retry", "action": "retry"}],
    "not_linked": [{"label": "Connect ORBIT", "action": "link_orbit"}],
    "unavailable": [{"label": "Retry", "action": "retry"}],
    "invalid": [{"label": "Retry", "action": "retry"}],
}


def relabel(items: list[ContextItem], start: int) -> list[ContextItem]:
    """Give items labels S{start}…, unique across all retrievals of one execution."""
    return [item.model_copy(update={"citation": f"S{start + i}"}) for i, item in enumerate(items)]


def scan(items: list[ContextItem]) -> list[ContextItem]:
    return [i.model_copy(update={"flagged_injection": detect_injection(f"{i.title}\n{i.excerpt}")}) for i in items]


def context_sources_block(
    state_items: list[ContextItem],
    *,
    project: str | None,
    retrieval_id: str | None,
    reference_id: str | None,
    warnings: list[str],
    excluded: int,
) -> Block:
    return Block(
        key="context",
        type=BlockType.context_sources,
        data={
            "project": project,
            "retrieval_id": retrieval_id,
            "reference_id": reference_id,
            "excluded_count": excluded,
            "warnings": warnings,
            "max_classification": max((i.classification for i in state_items), default=0),
            "items": [
                {
                    "citation": i.citation,
                    "ref_id": i.ref_id,
                    "title": i.title,
                    "kind": i.kind,
                    "type": i.memory_kind or i.source_kind,
                    "project": i.project_slug,
                    "source": i.source_system,
                    "uri": i.uri,
                    "updated": i.date.isoformat() if i.date else None,
                    "classification": i.classification,
                    "classification_label": CLASSIFICATION_LABELS.get(i.classification),
                    "relevance": round(i.relevance, 3) if i.relevance is not None else None,
                    "excerpt": i.excerpt[:400],
                    "flagged": i.flagged_injection,
                    "document_id": i.document_id,
                    "memory_item_id": i.memory_item_id,
                }
                for i in state_items
            ],
        },
    )


def classification_warnings(items: list[ContextItem]) -> list[str]:
    top = max((i.classification for i in items), default=0)
    if top >= 3:
        return ["This context includes C3 · Secret material. Outputs inherit this classification."]
    if top == 2:
        return ["This context includes C2 · Confidential material. Outputs inherit this classification."]
    return []


@node("retrieve_orbit_context")
async def retrieve_orbit_context(state: NovaState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    d = deps(runtime)
    c = state.classification
    updates: dict[str, Any] = {"phase": NovaPhase.retrieving_context}

    # FORGE evaluation: the context is prepared by FORGE (reproducible) — never call ORBIT.
    if state.origin == ExecutionOrigin.forge_protocol:
        items = scan(relabel(state.provided_context, 1))
        bundle = ContextBundle(retrieval_id=None, items=items)
        if items:
            ref = await d.store.record_context(
                task_id=state.task_id, user_id=state.user_id, conversation_id=None, query="forge-provided", bundle=bundle
            )
            updates["context_reference_id"] = ref
            items = [i.model_copy(update={"reference_id": ref}) for i in items]
        await progress(d, state, "context", "Using the provided context", "completed", f"{len(items)} sources provided")
        updates["context_items"] = items
        return updates

    if state.context_mode == "none" or (c and not c.needs_context and c.kind == IntentKind.smalltalk):
        return updates
    await set_phase(d, state, NovaPhase.retrieving_context, "Retrieving context")

    items: list[ContextItem] = []
    warnings: list[str] = []
    excluded = 0
    retrieval_id = None

    # Explicit context pinned by the user ("Add context") is re-used from what ORBIT served before.
    if state.pinned_context_ref_ids:
        for ref in await d.store.get_context_references(state.pinned_context_ref_ids, state.user_id):
            items += ref.items

    if state.context_mode == "auto":
        if not state.project_slug:
            await upsert(
                d,
                state,
                warning_block(
                    "No project selected",
                    "NOVA worked without project context. Choose a project to use ORBIT context.",
                    [{"label": "Choose a project", "action": "choose_project"}],
                    key="context_warning",
                ),
            )
            updates["context_issue"] = ContextIssue(code="no_project", message="No project selected")
        else:
            await progress(d, state, "context", "Retrieving context", "running")
            purpose = PURPOSE_BY_CATEGORY.get(c.category.value if c and c.category else "general", "general")
            query = (c.context_query if c and c.context_query else state.intent)[:7000]
            try:
                bundle = await d.context.retrieve(
                    ContextQuery(
                        user_id=state.user_id,
                        project_slug=state.project_slug,
                        task=query,
                        purpose=purpose,
                        token_budget=d.settings.orbit_default_token_budget,
                        session_id=state.conversation_id,
                        max_classification=d.settings.policy_max_classification,
                    )
                )
                items += bundle.items
                warnings += bundle.warnings
                excluded = bundle.excluded_count
                retrieval_id = bundle.retrieval_id
            except ContextError as exc:
                title, message = ERROR_COPY.get(exc.code, ERROR_COPY["unavailable"])
                await upsert(d, state, warning_block(title, message, ERROR_ACTIONS.get(exc.code, []), key="context_warning"))
                await progress(d, state, "context", "Retrieving context", "failed", message)
                updates["context_issue"] = ContextIssue(code=exc.code, message=exc.message, retryable=exc.retryable)

    removed = set(state.excluded_context_refs)  # ORBIT item ids removed by the user ("Remove context")
    items = [i for i in items if i.ref_id not in removed]
    seen: set[str] = set()
    unique = [i for i in items if not (i.ref_id in seen or seen.add(i.ref_id))]
    items = scan(relabel(unique, 1))
    warnings = list(dict.fromkeys([*warnings, *classification_warnings(items)]))

    if items:
        bundle = ContextBundle(
            retrieval_id=retrieval_id, project_slug=state.project_slug, items=items, warnings=warnings, excluded_count=excluded
        )
        reference_id = await d.store.record_context(
            task_id=state.task_id,
            user_id=state.user_id,
            conversation_id=state.conversation_id,
            query=state.intent[:2000],
            bundle=bundle,
        )
        updates["context_reference_id"] = reference_id
        items = [i.model_copy(update={"reference_id": reference_id}) for i in items]
        await upsert(
            d,
            state,
            context_sources_block(
                items,
                project=state.project_slug,
                retrieval_id=retrieval_id,
                reference_id=reference_id,
                warnings=warnings,
                excluded=excluded,
            ),
        )
        flagged = sum(1 for i in items if i.flagged_injection)
        detail = f"{len(items)} sources found" + (f" · {flagged} flagged as suspicious" if flagged else "")
        await progress(d, state, "context", "Retrieving context", "completed", detail)
    elif state.context_mode == "auto" and state.project_slug and "context_issue" not in updates:
        await progress(d, state, "context", "Retrieving context", "completed", "No relevant context found")

    updates.update(context_items=items, context_warnings=warnings, context_retrieval_id=retrieval_id)
    return updates
