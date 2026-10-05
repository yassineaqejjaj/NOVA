"""Sub-agents: every step runs under the persona of the agent owning its Skill; the user's profile steers planning."""

from __future__ import annotations

from nova.agent import prompts
from nova.artifacts.registry import get_artifact_registry
from nova.domain.state import NovaState
from nova.skills.registry import get_skill_registry


def _state(**prefs: str) -> NovaState:
    return NovaState(task_id="t", user_id="u", intent="Write the technical design of the export service", preferences=prefs)


def test_step_prompt_carries_the_sub_agent_persona():
    skill = get_skill_registry().get("technical-design")
    artifact_type = get_artifact_registry().get(skill.outputs.artifact_type)
    messages = prompts.skill_step_messages(
        _state(),
        skill,
        skill.steps[0],
        artifact_type,
        fills=skill.steps[0].fills,
        produced={},
        existing=None,
        previous_outputs=[],
        tool_results=[],
        tools_allowed=[],
    )
    system = messages[0].content
    assert "SUB-AGENT: you are NOVA's Engineering agent" in system
    assert "non-functional concerns" in system
    assert system.index("SUB-AGENT") < system.index("SKILL: Technical Design")


def test_planning_shows_agents_and_prefers_the_user_profile():
    registry = get_skill_registry()
    candidates = [registry.get("technical-design"), registry.get("design-brief")]
    user = prompts.plan_messages(_state(profile="design"), candidates, can_ask=False)
    assert "- design-brief: Design Brief (Design agent)" in user[1].content
    assert "prefer the Design agent's" in user[0].content
    assert "of a design professional" in user[0].content
    assert "prefer the" not in prompts.plan_messages(_state(), candidates, can_ask=False)[0].content
