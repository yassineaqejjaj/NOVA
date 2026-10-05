"""Prompt assembly for every model call.

Order follows the trust hierarchy: system rules, organization rules, Skill instructions, user
instructions, retrieved context (as untrusted data), tool results (as untrusted data).
"""

from __future__ import annotations

import json
from typing import Any

from nova.agent.ports import ArtifactOutline, ArtifactSnapshot
from nova.domain.agents import AGENTS, AgentProfile, agent_instructions
from nova.domain.artifacts import ArtifactType, SectionContent
from nova.domain.context import ContextItem
from nova.domain.llm import LLMMessage
from nova.domain.outputs import ToolResult
from nova.domain.skills import SkillSpec, SkillStep
from nova.domain.state import NovaState
from nova.domain.trust import TRUST_RULES, wrap_untrusted

ORGANIZATION_RULES = """\
ORGANIZATION RULES: respect data classification (C0 public … C3 secret) — never move content to a
less protected place; product decisions recorded in project context prevail over assumptions; prefer
precise, testable language; write in the user's language."""

MAX_CONTEXT_CHARS = 14000
MAX_PREVIOUS_CHARS = 6000


def _identity(state: NovaState) -> str:
    prefs = state.preferences
    name = prefs.get("nova_name") or "NOVA"
    tone = prefs.get("tone") or "clear and concise"
    profile = _profile(state)
    role = prefs.get("role") or (f"{profile.value} professional" if profile else "product professional")
    methods = ", ".join(prefs.get("preferred_methods") or []) or "no particular preference"
    team = ", ".join(a.name for a in AGENTS.values())
    return (
        f"You are {name}, the personal AI product agent of a {role}. You help them execute product work "
        f"across the software development lifecycle, orchestrating specialist sub-agents ({team}). "
        f"Tone: {tone}. Preferred methods: {methods}."
    )


def _profile(state: NovaState) -> AgentProfile | None:
    value = state.preferences.get("profile")
    return AgentProfile(value) if value in AgentProfile.__members__ else None


def system_message(state: NovaState, extra: str = "") -> LLMMessage:
    parts = [_identity(state), TRUST_RULES, ORGANIZATION_RULES]
    if extra:
        parts.append(extra)
    return LLMMessage(role="system", content="\n\n".join(parts))


def context_block(items: list[ContextItem], max_chars: int = MAX_CONTEXT_CHARS) -> str:
    if not items:
        return "CONTEXT: none available."
    chunks, used = [], 0
    for item in items:
        header = f"{item.kind}/{item.memory_kind or item.source_kind or 'source'} · C{item.classification}"
        if item.date:
            header += f" · {item.date.date().isoformat()}"
        body = f"{header}\n{item.excerpt}"
        envelope = wrap_untrusted(item.source_system, item.citation, item.title, body, flagged=item.flagged_injection)
        if used + len(envelope) > max_chars:
            break
        chunks.append(envelope)
        used += len(envelope)
    return "CONTEXT (cite with the label):\n" + "\n".join(chunks)


def tool_results_block(results: list[ToolResult]) -> str:
    if not results:
        return ""
    chunks = []
    for i, result in enumerate(results, 1):
        body = json.dumps(result.output if result.status == "ok" else {"error": result.error}, ensure_ascii=False)[:3000]
        chunks.append(wrap_untrusted(f"tool:{result.tool}", f"T{i}", result.tool, body))
    return "TOOL RESULTS:\n" + "\n".join(chunks)


def history_block(state: NovaState) -> str:
    if not state.history:
        return ""
    lines = [f"{h['role']}: {h['text'][:600]}" for h in state.history[-6:]]
    return "RECENT CONVERSATION:\n" + "\n".join(lines)


# --- understand_intent ---------------------------------------------------------------------------


def intent_messages(
    state: NovaState, catalog: list[SkillSpec], outlines: list[ArtifactOutline], artifact_types: list[str]
) -> list[LLMMessage]:
    artifacts = (
        "\n".join(
            f"- id={o.artifact_id} type={o.type} title={o.title!r} v{o.version} sections={','.join(o.sections)}"
            + (" items=" + "; ".join(f"{i['id']}:{i['title'][:60]}" for i in o.items[:40]) if o.items else "")
            for o in outlines
        )
        or "none"
    )
    active = f"\nThe user is currently viewing artifact id={state.active_artifact_id}." if state.active_artifact_id else ""
    skills = "\n".join(s.catalog_line() for s in catalog)
    instructions = """\
Classify the user's request.
- kind: run_workflow (produce product work: documents, plans, backlogs, analyses…), edit_artifact (change part
  of an existing artifact), explain_provenance (asks why something is in an artifact / where it comes from),
  question (wants an answer, no document), smalltalk.
- For edit_artifact / explain_provenance, set target_artifact_id (only ids listed below), target_sections
  (section keys of that artifact) and target_item_id when the user points to a specific item.
- context_query: what to look up in the project knowledge to do this well.
- candidate_skill_ids: up to 6 relevant skills from the catalog, best first."""
    user = (
        f"USER REQUEST:\n{state.intent}\n{active}\n\n{history_block(state)}\n\n"
        f"AVAILABLE ARTIFACTS:\n{artifacts}\n\nARTIFACT TYPES: {', '.join(artifact_types)}\n\n"
        f"SKILL CATALOG:\n{skills}"
    )
    return [system_message(state, instructions), LLMMessage(role="user", content=user)]


# --- plan_execution ------------------------------------------------------------------------------


def plan_messages(state: NovaState, candidates: list[SkillSpec], *, can_ask: bool) -> list[LLMMessage]:
    lines = []
    for skill in candidates:
        required = [f"{i.name} ({i.description})" for i in skill.required_inputs]
        lines.append(
            f"- {skill.id}: {skill.name} ({AGENTS[skill.agent].name}) — {skill.summary} Output: {skill.outputs.artifact_type}."
            + (f" Required inputs: {'; '.join(required)}." if required else "")
            + (f" Often followed by: {', '.join(skill.composes_with)}." if skill.composes_with else "")
        )
    ask_rule = (
        "- missing_inputs: ONLY required inputs of the chosen skills that are neither in the request, the "
        "answers already given nor the context. Ask nothing else. Ask at most 3 questions."
        if can_ask
        else "- You cannot ask questions: leave missing_inputs empty and list your assumptions instead."
    )
    profile = _profile(state)
    profile_rule = (
        f"\n- The user works as a {profile.value} professional: when skills of several agents fit equally, prefer the "
        f"{AGENTS[profile].name}'s."
        if profile
        else ""
    )
    instructions = f"""\
Plan the work as a short workflow of skills (1 to {state_max_steps(state)} steps) that achieves the user's goal.
- Use only skill ids from CANDIDATE SKILLS. One skill per step, in execution order.
- Prefer the smallest workflow that fully serves the goal; chain skills only when the user's goal needs them.
- If the user asks for a specific deliverable (a PRD, a backlog, a sprint plan…), the skill that produces it MUST be
  in the plan. Never replace it with smaller skills whose content it already covers.
- Decompose the goal: each step gets a short operational title ("Frame the problem", "Write the PRD"), a goal (what
  this step must deliver toward the user's goal) and a rationale (why this Skill). NOVA assigns each step to the
  sub-agent that owns its Skill. Write titles, goals and rationales in the user's language.
{ask_rule}{profile_rule}"""
    answers = "\n".join(f"- {k}: {v}" for k, v in state.user_inputs.items()) or "none"
    context_titles = "\n".join(f"- [{i.citation}] {i.title}" for i in state.context_items[:30]) or "none"
    goal = state.classification.goal if state.classification else state.intent
    user = (
        f"GOAL: {goal}\nUSER REQUEST:\n{state.intent}\n\nANSWERS ALREADY GIVEN:\n{answers}\n\n"
        f"AVAILABLE CONTEXT (titles only):\n{context_titles}\n\nCANDIDATE SKILLS:\n" + "\n".join(lines)
    )
    return [system_message(state, instructions), LLMMessage(role="user", content=user)]


def state_max_steps(state: NovaState) -> int:
    return int(state.preferences.get("max_workflow_steps") or 8)


# --- execute_skill -------------------------------------------------------------------------------


def _sections_json(sections: dict[str, SectionContent], keys: list[str] | None = None) -> str:
    data = {k: v.model_dump(mode="json", exclude_defaults=True) for k, v in sections.items() if keys is None or k in keys}
    return json.dumps(data, ensure_ascii=False)


def skill_step_messages(
    state: NovaState,
    skill: SkillSpec,
    step: SkillStep,
    artifact_type: ArtifactType,
    *,
    fills: list[str],
    produced: dict[str, SectionContent],
    existing: ArtifactSnapshot | None,
    previous_outputs: list[str],
    tool_results: list[ToolResult],
    tools_allowed: list[str],
    edit_instruction: str | None = None,
) -> list[LLMMessage]:
    principles = "\n".join(f"- {p}" for p in skill.methodology.principles)
    skill_text = (
        f"{agent_instructions(skill.agent)}\n\n"
        f"SKILL: {skill.name} v{skill.version} — {skill.purpose}\n"
        f"METHOD: {skill.methodology.name}\n{principles}\n\nSKILL INSTRUCTIONS:\n{skill.instructions}"
    )
    tools_text = ""
    if tools_allowed:
        tools_text = (
            "\nTOOLS you may request (set tool_requests, then you will get the results): "
            + ", ".join(tools_allowed)
            + ". Request tools only if the context is insufficient for this step; otherwise leave tool_requests empty."
        )
    section_help = "\n".join(
        f"- {key}: {d.title} ({d.kind}{', items of kind ' + d.item_kind if d.item_kind else ''})"
        + (f" — {d.description}" if d.description else "")
        for key in fills
        if (d := artifact_type.section(key))
    )
    parts = [f"GOAL: {state.classification.goal if state.classification else state.intent}", f"USER REQUEST:\n{state.intent}"]
    plan_step = state.plan.step(state.current_step) if state.plan and state.current_step else None
    if plan_step and plan_step.goal:
        parts.append(f"YOUR ASSIGNMENT FROM NOVA (step '{plan_step.title}'): {plan_step.goal}")
    if state.user_inputs:
        parts.append("USER ANSWERS:\n" + "\n".join(f"- {k}: {v}" for k, v in state.user_inputs.items()))
    if state.attachments:
        parts.append(
            "ATTACHED BY THE USER:\n"
            + "\n".join(
                wrap_untrusted("attachment", a.get("name", "file"), a.get("name", "file"), a.get("text", "")[:4000])
                for a in state.attachments
            )
        )
    if previous_outputs:
        parts.append("RESULTS OF PREVIOUS STEPS (use them as input):\n" + "\n\n".join(previous_outputs)[:MAX_PREVIOUS_CHARS])
    if existing is not None:
        parts.append(
            f"CURRENT ARTIFACT '{existing.title}' ({existing.type} v{existing.version}) — sections to update:\n"
            + _sections_json(existing.content.sections, fills)
        )
    if produced:
        parts.append("ALREADY PRODUCED IN THIS SKILL (keep consistent, reference ids as parent_id):\n" + _sections_json(produced))
    parts.append(context_block(state.context_items))
    if tool_results:
        parts.append(tool_results_block(tool_results))
    if edit_instruction:
        parts.append(f"EDIT INSTRUCTION: {edit_instruction}\nReturn only the sections that must change.")
    parts.append(
        f"CURRENT STEP — {step.title}:\n{step.instruction}\n\nSECTIONS TO FILL:\n{section_help}\n"
        f"Write in the language of the user's request ('{state.classification.response_language if state.classification else 'en'}'), "
        "even when the context is in another language."
    )
    return [system_message(state, skill_text + tools_text), LLMMessage(role="user", content="\n\n".join(parts))]


# --- validate_step (NOVA's Validation agent) -----------------------------------------------------

VALIDATION_AGENT = """\
SUB-AGENT: you are NOVA's Validation agent — it verifies every deliverable before NOVA hands it over.
PROFESSIONAL STANDARDS:
- Judge the deliverable against the user's goal, the Skill's criteria and the project context, not your own taste
- Ask for a revision only for problems that matter to the user (wrong, missing, unsupported or unusable content)
- Be specific: name the section, the problem and the fix; never rewrite the content yourself"""


def review_messages(
    state: NovaState,
    skill: SkillSpec,
    artifact_type: ArtifactType,
    sections: dict[str, SectionContent],
    *,
    step_goal: str,
    failed_checks: list[str],
) -> list[LLMMessage]:
    criteria = "\n".join(f"- {c.get('key')}: {c.get('question')}" for c in skill.evaluation.criteria) or "- none"
    keys = "\n".join(f"- {key}: {d.title}" for key in sections if (d := artifact_type.section(key)))
    lang = state.classification.response_language if state.classification else "en"
    instructions = (
        f"{VALIDATION_AGENT}\n\nReview the {artifact_type.name} produced by NOVA's {AGENTS[skill.agent].name} "
        f"with the Skill {skill.name} ({skill.methodology.name}). Grade every criterion; verdict 'revise' only when "
        f"an issue matters. At most 4 issues. Write comments, problems, fixes and summary in '{lang}'."
    )
    parts = [
        f"USER GOAL: {state.classification.goal if state.classification else state.intent}",
        f"STEP GOAL: {step_goal or skill.summary}",
        f"CRITERIA:\n{criteria}",
        f"SECTIONS (keys):\n{keys}",
        "DELIVERABLE:\n" + _sections_json(sections)[: MAX_PREVIOUS_CHARS * 2],
    ]
    if failed_checks:
        parts.append("AUTOMATED CHECKS THAT FAILED:\n" + "\n".join(f"- {c}" for c in failed_checks))
    parts.append(context_block(state.context_items, max_chars=MAX_CONTEXT_CHARS // 2))
    return [system_message(state, instructions), LLMMessage(role="user", content="\n\n".join(parts))]


# --- answers -----------------------------------------------------------------------------------


def _language(state: NovaState) -> str:
    lang = state.classification.response_language if state.classification else "en"
    return f"Answer in the same language as the user's request (detected: {lang}), even if the context is in another language."


def answer_messages(state: NovaState, extra: str = "") -> list[LLMMessage]:
    instructions = (
        "Answer the user's question using the context when relevant. Cite labels like [S1] for facts taken "
        "from context and list them in citations. If the context does not contain the answer, say so plainly. " + _language(state)
    )
    user = f"{history_block(state)}\n\nQUESTION:\n{state.intent}\n\n{context_block(state.context_items)}\n{extra}"
    return [system_message(state, instructions), LLMMessage(role="user", content=user.strip())]


def provenance_messages(state: NovaState, item_summary: str, sources: list[dict[str, Any]]) -> list[LLMMessage]:
    instructions = (
        "Explain to the user why this element is in the artifact, using ONLY the recorded rationale and the "
        "recorded sources below. Do not add any other source. If no source is recorded, say that the element "
        "was proposed by NOVA from the user's input and explain the recorded rationale. " + _language(state)
    )
    src = "\n".join(wrap_untrusted("orbit", s["label"], s["title"], s.get("excerpt", "")) for s in sources) or "none recorded"
    user = f"QUESTION: {state.intent}\n\nELEMENT:\n{item_summary}\n\nRECORDED SOURCES:\n{src}"
    return [system_message(state, instructions), LLMMessage(role="user", content=user)]
