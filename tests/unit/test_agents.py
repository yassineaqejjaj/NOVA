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


def test_later_steps_get_an_outline_of_earlier_sections_and_a_revision_the_full_content():
    from nova.domain.artifacts import ArtifactItem, SectionContent, TextBlock
    from nova.domain.enums import SectionKind

    skill = get_skill_registry().get("prd")
    artifact_type = get_artifact_registry().get(skill.outputs.artifact_type)
    long_text = "Exports are sent by hand every Monday. " * 30
    produced = {
        "summary": SectionContent(kind=SectionKind.rich_text, blocks=[TextBlock(type="paragraph", text=long_text)]),
        "scope": SectionContent(
            kind=SectionKind.items,
            items=[ArtifactItem(id="scope-1", kind="note", title="Scheduled exports", description="Weekly CSV " * 20)],
        ),
    }

    def user_prompt(**kw) -> str:
        step = skill.steps[2]
        return prompts.skill_step_messages(
            _state(), skill, step, artifact_type, fills=step.fills, produced=produced, existing=None,
            previous_outputs=[], tool_results=[], tools_allowed=[], **kw,
        )[1].content  # fmt: skip

    outline = user_prompt()
    assert "- scope-1: Scheduled exports — Weekly CSV" in outline and "…" in outline
    assert long_text not in outline and '"blocks"' not in outline  # abridged, no JSON
    revision = user_prompt(full=["scope"])
    assert "SECTIONS UNDER REVISION (full content):" in revision and '"scope-1"' in revision
    assert ("Weekly CSV " * 20).strip() in revision


def test_the_validation_agent_reads_the_deliverable_as_markdown():
    from nova.domain.artifacts import ArtifactItem, SectionContent
    from nova.domain.enums import SectionKind

    skill = get_skill_registry().get("prd")
    artifact_type = get_artifact_registry().get(skill.outputs.artifact_type)
    sections = {"scope": SectionContent(kind=SectionKind.items, items=[ArtifactItem(id="s1", kind="note", title="Exports")])}
    user = prompts.review_messages(_state(), skill, artifact_type, sections, step_goal="", failed_checks=[])[1].content
    assert "#### scope: " in user and "- **Exports**" in user and '"items"' not in user
