"""Training loop, pure parts: lesson distillation, promotion rule, prompt injection, FORGE mapping."""

from __future__ import annotations

from nova.agent import prompts
from nova.artifacts.registry import get_artifact_registry
from nova.domain.agents import AgentProfile, agent_instructions
from nova.domain.learning import (
    MAX_SKILL_LESSONS,
    AgentLearning,
    SkillFeedback,
    distill,
    lesson_from_recommendation,
    promotion_decision,
)
from nova.domain.state import NovaState
from nova.integrations.forge import mapper
from nova.skills.registry import get_skill_registry


def rec(title: str, description: str = "", *, category: str = "system_prompt", priority: str = "p1", **extra) -> dict:
    return {"category": category, "priority": priority, "title": title, "description": description, **extra}


def test_only_prompt_recommendations_become_lessons_and_evidence_is_never_copied():
    lesson = lesson_from_recommendation(
        rec(
            "Citer les sources",
            "Ajouter une consigne explicite de citer chaque affirmation.",
            evidence=[{"excerpt": "Client ACME, 42 rue X"}],
        )
    )
    assert lesson == "Citer les sources: Ajouter une consigne explicite de citer chaque affirmation."
    assert "ACME" not in lesson
    assert lesson_from_recommendation(rec("Changer de modèle", category="model")) is None
    assert lesson_from_recommendation(rec("Détail mineur", priority="p2")) is None


def test_distill_merges_lessons_promotes_shared_ones_and_keeps_other_advice():
    shared = rec("Cite every claim", "Link each statement to a context source.")
    feedback = [
        SkillFeedback(skill_id="prd", score=0.6, recommendations=[shared, rec("Quantify success metrics")], report_id="r1"),
        SkillFeedback(skill_id="persona", score=0.7, recommendations=[shared]),
        SkillFeedback(skill_id="okr-definition", score=0.5, recommendations=[shared, rec("Retrieve more", category="retrieval")]),
        SkillFeedback(skill_id="kano-analysis", score=0.9, recommendations=[]),
    ]
    current = AgentLearning(skills={"prd": ["Keep the problem statement short."]})
    result = distill(feedback, current)
    assert result.standards == ["Cite every claim: Link each statement to a context source."]
    assert result.new_standards == result.standards
    # Shared lessons move to the agent standards; specific ones stay on the Skill, before the older ones
    assert result.skills["prd"] == ["Quantify success metrics", "Keep the problem statement short."]
    assert "persona" not in result.skills and "okr-definition" not in result.skills
    assert result.changed_skills == ["prd"] and result.changed
    assert result.other_recommendations[0]["category"] == "retrieval"
    assert result.report_ids == ["r1"]


def test_distill_is_stable_when_nothing_new_is_learned():
    current = AgentLearning(skills={"prd": ["Quantify success metrics"]})
    again = distill([SkillFeedback(skill_id="prd", recommendations=[rec("Quantify success metrics")])], current)
    assert not again.changed and again.skills == current.skills
    many = distill([SkillFeedback(skill_id="prd", recommendations=[rec(f"Lesson {i}") for i in range(9)])], None)
    assert len(many.skills["prd"]) == MAX_SKILL_LESSONS


def test_promotion_rule():
    assert promotion_decision({"recommendation": {"recommendation": "ship"}}).promote
    caution = {"recommendation": {"recommendation": "ship_with_caution"}, "composite": {"delta": 0.03}, "regressions": []}
    assert promotion_decision(caution).promote
    assert not promotion_decision({**caution, "regressions": [{"severity": "critical"}]}).promote
    assert not promotion_decision({**caution, "composite": {"delta": 0.0}}).promote
    assert not promotion_decision({"recommendation": {"recommendation": "inconclusive"}}).promote
    assert not promotion_decision({"recommendation": {"recommendation": "do_not_ship"}}).promote
    assert not promotion_decision({}).promote


def test_learned_lessons_reach_the_specialist_and_the_validation_agent():
    registry = get_skill_registry()
    skill = registry.get("prd")
    snapshot = {
        "product": AgentLearning(
            policy_id="p", version=2, standards=["Always state the target segment."], skills={"prd": ["Quantify the goal."]}
        ).model_dump()
    }
    state = NovaState(task_id="t", user_id="u", intent="Write a PRD", learning=snapshot)
    artifact_type = get_artifact_registry().get(skill.outputs.artifact_type)
    step = skill.steps[0]
    messages = prompts.skill_step_messages(
        state,
        skill,
        step,
        artifact_type,
        fills=step.fills,
        produced={},
        existing=None,
        previous_outputs=[],
        tool_results=[],
        tools_allowed=[],
    )
    system = messages[0].content
    assert "LEARNED STANDARDS" in system and "Always state the target segment." in system
    assert "LESSONS FROM PAST EVALUATIONS OF THIS SKILL" in system and "Quantify the goal." in system
    review = prompts.review_messages(state, skill, artifact_type, {}, step_goal="", failed_checks=[])
    assert "learned: Quantify the goal." in review[1].content
    # Another agent's lessons never leak into this agent's prompt
    assert "LEARNED STANDARDS" not in agent_instructions(AgentProfile.design, [])
    bare = prompts.skill_step_messages(
        NovaState(task_id="t", user_id="u", intent="Write a PRD"),
        skill,
        step,
        artifact_type,
        fills=step.fills,
        produced={},
        existing=None,
        previous_outputs=[],
        tool_results=[],
        tools_allowed=[],
    )
    assert "LESSONS FROM PAST EVALUATIONS" not in bare[0].content


def test_every_skill_gets_a_valid_training_scenario():
    registry = get_skill_registry()
    slugs = set()
    for skill in registry.all():
        if skill.system:
            continue
        body = mapper.training_scenario_body(skill)
        assert body["classification"] == 1 and body["visibility"] == "public"  # synthetic C1 pack only
        assert body["content"]["input"]["nova_skill"] == skill.id
        assert f"agent:{skill.agent.value}" in body["tags"]
        assert all(
            c["key"].split(".")[0] in {"quality", "coherence", "reasoning", "safety", "ux"}
            for c in body["content"].get("criteria", [])
        )
        slugs.add(body["slug"])
    assert len(slugs) == sum(1 for s in registry.all() if not s.system)
    assert mapper.profile_of("nova-design") == AgentProfile.design
    assert mapper.profile_of("nova-orchestrator") is None and mapper.profile_of("nova-unknown") is None


def test_c2_production_capture_is_private_in_forge():
    from nova.domain.evaluation import ExecutionRecord

    base = {
        "task_id": "t",
        "trace_id": None,
        "user_intent": "Write a PRD",
        "origin": "interactive",
        "agent_version": "1.0.0",
        "model": None,
        "status": "completed",
    }
    record = ExecutionRecord.model_validate({**base, "context_max_classification": 2})
    assert mapper.scenario_body(record)["visibility"] == "private"
    record = ExecutionRecord.model_validate({**base, "context_max_classification": 1})
    assert mapper.scenario_body(record)["visibility"] == "public"


def test_forge_view_cites_the_forge_documents():
    from nova_api.routers.forge_protocol import forge_citations

    provided = [{"citation": "S1", "ref_id": "relais-brief"}, {"citation": "S2", "ref_id": "relais-research"}]
    text = "Technicians lose 40 minutes [S1] [S2]; unknown [S9]."
    assert forge_citations(text, provided) == (
        "Technicians lose 40 minutes [source: relais-brief] [source: relais-research]; unknown [S9]."
    )
