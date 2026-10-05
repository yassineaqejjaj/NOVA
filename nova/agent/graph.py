"""The NOVA execution graph (docs/ARCHITECTURE.md §5).

START → understand_intent → retrieve_orbit_context → (plan_execution | plan_edit | answer_question |
explain_provenance) → [request_user_input] → [confirm_workflow] → select_skills → execute_skill ⇄
execute_tools → validate_step (Validation agent, one revision) → generate_artifact → [request_approval] → … → finalize → emit_forge_trace → END
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Checkpointer, RetryPolicy

from nova.agent.deps import AgentDeps
from nova.agent.nodes.answers import answer_question, explain_provenance
from nova.agent.nodes.context import retrieve_orbit_context
from nova.agent.nodes.execution import execute_skill, execute_tools, generate_artifact, validate_step
from nova.agent.nodes.finalize import emit_forge_trace, finalize
from nova.agent.nodes.intent import understand_intent
from nova.agent.nodes.interaction import confirm_workflow, request_approval, request_user_input
from nova.agent.nodes.planning import plan_edit, plan_execution, select_skills
from nova.domain.enums import IntentKind
from nova.domain.llm import LLMError
from nova.domain.state import NovaState


def _retry_on(exc: Exception) -> bool:
    if isinstance(exc, LLMError):
        return exc.retryable
    return isinstance(exc, (TimeoutError, ConnectionError))


MODEL_RETRY = RetryPolicy(max_attempts=3, initial_interval=1.0, backoff_factor=2.0, retry_on=_retry_on)


def _failed(state: NovaState) -> bool:
    return state.status in ("failed", "cancelled")


def after_intent(state: NovaState) -> str:
    if _failed(state):
        return "finalize"
    kind = state.classification.kind if state.classification else IntentKind.run_workflow
    if kind == IntentKind.smalltalk:
        return "answer_question"
    if kind == IntentKind.explain_provenance:
        return "explain_provenance"
    return "retrieve_orbit_context"


def after_context(state: NovaState) -> str:
    if _failed(state):
        return "finalize"
    kind = state.classification.kind if state.classification else IntentKind.run_workflow
    if kind == IntentKind.question:
        return "answer_question"
    if kind == IntentKind.edit_artifact:
        return "plan_edit"
    return "plan_execution"


def after_questions(state: NovaState) -> str:
    if _failed(state):
        return "finalize"
    return "plan_execution"  # re-plan with the answers (skills may change once the idea is known)


def after_confirm(state: NovaState) -> str:
    return "finalize" if _failed(state) else "select_skills"


def after_select(state: NovaState) -> str:
    if _failed(state):
        return "finalize"
    return "execute_skill" if state.current_step else "finalize"


def after_execute(state: NovaState) -> str:
    if _failed(state):
        return "finalize"
    if state.pending_tool_requests:
        return "execute_tools"
    out = state.step_outputs.get(state.current_step or "")
    return "validate_step" if out and out.done else "execute_skill"


def after_validate(state: NovaState) -> str:
    return "finalize" if _failed(state) else "generate_artifact"


def after_tools(state: NovaState) -> str:
    return "finalize" if _failed(state) else "execute_skill"


def after_artifact(state: NovaState) -> str:
    if _failed(state):
        return "finalize"
    if state.requires_approval and state.approval:
        return "request_approval"
    return "select_skills" if state.plan and state.plan.next_pending() else "finalize"


def after_approval(state: NovaState) -> str:
    return "select_skills" if state.plan and state.plan.next_pending() else "finalize"


def build_graph(checkpointer: Checkpointer | None = None):
    graph = StateGraph(NovaState, context_schema=AgentDeps)
    graph.add_node("understand_intent", understand_intent, retry_policy=MODEL_RETRY)
    graph.add_node("retrieve_orbit_context", retrieve_orbit_context, retry_policy=MODEL_RETRY)
    graph.add_node("plan_execution", plan_execution, retry_policy=MODEL_RETRY)
    graph.add_node("plan_edit", plan_edit)
    graph.add_node("request_user_input", request_user_input)
    graph.add_node("confirm_workflow", confirm_workflow)
    graph.add_node("select_skills", select_skills)
    graph.add_node("execute_skill", execute_skill, retry_policy=MODEL_RETRY)
    graph.add_node("execute_tools", execute_tools)
    graph.add_node("validate_step", validate_step, retry_policy=MODEL_RETRY)
    graph.add_node("generate_artifact", generate_artifact)
    graph.add_node("request_approval", request_approval)
    graph.add_node("answer_question", answer_question, retry_policy=MODEL_RETRY)
    graph.add_node("explain_provenance", explain_provenance, retry_policy=MODEL_RETRY)
    graph.add_node("finalize", finalize)
    graph.add_node("emit_forge_trace", emit_forge_trace)

    graph.add_edge(START, "understand_intent")
    graph.add_conditional_edges(
        "understand_intent", after_intent, ["retrieve_orbit_context", "answer_question", "explain_provenance", "finalize"]
    )
    graph.add_conditional_edges(
        "retrieve_orbit_context", after_context, ["plan_execution", "plan_edit", "answer_question", "finalize"]
    )
    graph.add_conditional_edges(
        "plan_execution", _route_after_plan, ["request_user_input", "confirm_workflow", "select_skills", "finalize"]
    )
    graph.add_conditional_edges(
        "plan_edit", lambda s: "finalize" if _failed(s) else "select_skills", ["select_skills", "finalize"]
    )
    graph.add_conditional_edges("request_user_input", after_questions, ["plan_execution", "finalize"])
    graph.add_conditional_edges("confirm_workflow", after_confirm, ["select_skills", "finalize"])
    graph.add_conditional_edges("select_skills", after_select, ["execute_skill", "finalize"])
    graph.add_conditional_edges("execute_skill", after_execute, ["execute_tools", "validate_step", "execute_skill", "finalize"])
    graph.add_conditional_edges("validate_step", after_validate, ["generate_artifact", "finalize"])
    graph.add_conditional_edges("execute_tools", after_tools, ["execute_skill", "finalize"])
    graph.add_conditional_edges("generate_artifact", after_artifact, ["request_approval", "select_skills", "finalize"])
    graph.add_conditional_edges("request_approval", after_approval, ["select_skills", "finalize"])
    graph.add_edge("answer_question", "finalize")
    graph.add_edge("explain_provenance", "finalize")
    graph.add_edge("finalize", "emit_forge_trace")
    graph.add_edge("emit_forge_trace", END)
    return graph.compile(checkpointer=checkpointer)


def _route_after_plan(state: NovaState) -> str:
    if _failed(state) or state.plan is None:
        return "finalize"
    if state.pending_questions:
        return "request_user_input"
    return "select_skills" if state.plan.confirmed else "confirm_workflow"
