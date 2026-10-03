"""answer_question / explain_provenance — answers without creating an Artifact."""

from __future__ import annotations

import re
from typing import Any

from langgraph.runtime import Runtime

from nova.agent import prompts
from nova.agent.deps import AgentDeps
from nova.agent.nodes.common import NodeFailure, deps, node, progress, set_phase, upsert
from nova.domain.artifacts import Citation
from nova.domain.blocks import Block, text_block
from nova.domain.context import ContextItem
from nova.domain.enums import CLASSIFICATION_LABELS, BlockType, IntentKind, NovaPhase
from nova.domain.outputs import AnswerOutput
from nova.domain.state import Answer, NovaState

_LABEL = re.compile(r"\[(S\d+)\]")


def strip_unknown_labels(text: str, known: set[str]) -> str:
    return _LABEL.sub(lambda m: m.group(0) if m.group(1) in known else "", text)


def source_view(item: ContextItem) -> dict[str, Any]:
    return {
        "label": item.citation,
        "title": item.title,
        "type": item.memory_kind or item.source_kind,
        "kind": item.kind,
        "source": item.source_system,
        "project": item.project_slug,
        "uri": item.uri,
        "updated": item.date.isoformat() if item.date else None,
        "classification": item.classification,
        "classification_label": CLASSIFICATION_LABELS.get(item.classification),
        "excerpt": item.excerpt[:500],
        "document_id": item.document_id,
        "memory_item_id": item.memory_item_id,
        "reference_id": item.reference_id,
    }


@node("answer_question")
async def answer_question(state: NovaState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    d = deps(runtime)
    await set_phase(d, state, NovaPhase.executing, "Preparing the answer")
    result = await d.llm.structured_output(prompts.answer_messages(state), AnswerOutput)
    by_label = {i.citation: i for i in state.context_items}
    used = [label for label in dict.fromkeys(result.value.citations + _LABEL.findall(result.value.answer)) if label in by_label]
    text = strip_unknown_labels(result.value.answer, set(by_label))
    block = text_block(text)
    block.data["follow_ups"] = result.value.follow_ups
    await upsert(d, state, block)
    if used:
        await upsert(
            d,
            state,
            Block(key="citations", type=BlockType.citations, data={"sources": [source_view(by_label[label]) for label in used]}),
        )
    return {
        "answer": Answer(text=text, citations=used, follow_ups=result.value.follow_ups),
        "usage": state.usage.add(result.usage),
        "model": result.model,
    }


@node("explain_provenance")
async def explain_provenance(state: NovaState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    """Explain why an element is in an Artifact from what was **recorded** at generation time."""
    d = deps(runtime)
    c = state.classification
    assert c is not None and c.kind == IntentKind.explain_provenance
    await set_phase(d, state, NovaPhase.retrieving_context, "Looking up the sources")
    snapshot = await d.store.get_artifact(c.target_artifact_id or "", state.user_id)
    if snapshot is None:
        raise NodeFailure("artifact_not_found", "NOVA can't access this Artifact.")
    artifact_type = d.artifacts.get(snapshot.type)

    citations: list[Citation] = []
    if c.target_item_id and (found := snapshot.content.find_item(c.target_item_id)):
        section_key, item = found
        title = artifact_type.section(section_key).title if artifact_type.section(section_key) else section_key  # type: ignore[union-attr]
        element = (
            f"{item.kind} '{item.title}' in section {title}: {item.description}\nRecorded rationale: {item.rationale or 'none'}"
        )
        citations = item.citations
    else:
        keys = c.target_sections or []
        if not keys:
            raise NodeFailure("element_unclear", "Which element do you mean? Select it in the Artifact or quote it.")
        parts = []
        for key in keys:
            section = snapshot.content.sections.get(key)
            if section is None:
                continue
            parts.append(f"Section {artifact_type.section(key).title if artifact_type.section(key) else key}")  # type: ignore[union-attr]
            citations += [cit for b in section.blocks for cit in b.citations]
            citations += [cit for i in section.items for cit in i.citations]
        element = "; ".join(parts)

    # Resolve only recorded citations — never re-search and present new sources as provenance.
    refs = await d.store.get_context_references(sorted({cit.ref for cit in citations if cit.ref}), state.user_id)
    items_by_ref = {(r.id, i.citation): i for r in refs for i in r.items}
    sources = []
    for cit in citations:
        item = items_by_ref.get((cit.ref or "", cit.label))
        if item and all(s["label"] != cit.label or s["reference_id"] != cit.ref for s in sources):
            sources.append(source_view(item.model_copy(update={"reference_id": cit.ref})))

    await progress(
        d,
        state,
        "provenance",
        "Looking up the sources",
        "completed",
        f"{len(sources)} recorded source{'s' if len(sources) != 1 else ''}",
    )
    result = await d.llm.structured_output(prompts.provenance_messages(state, element, sources), AnswerOutput)
    known = {s["label"] for s in sources}
    text = strip_unknown_labels(result.value.answer, known)
    if not sources:
        text += "\n\n_No ORBIT source was recorded for this element: it was proposed by NOVA from your request._"
    await upsert(d, state, text_block(text))
    await upsert(
        d,
        state,
        Block(
            key="citations",
            type=BlockType.citations,
            data={"artifact_id": snapshot.artifact_id, "sources": sources, "provenance": True},
        ),
    )
    return {
        "answer": Answer(text=text, citations=sorted(known), provenance=sources),
        "usage": state.usage.add(result.usage),
        "model": result.model,
    }
