"""Dynamic team assembly: measured performance as a tie-breaker, mission constraints, the recorded team."""

from __future__ import annotations

from types import SimpleNamespace

from nova.agent.nodes.execution import constrained_tools
from nova.agent.tools.registry import get_tool_registry
from nova.domain.assembly import MAX_BONUS, build_team, performance_bonus, withholds_external_writes
from nova.skills.registry import get_skill_registry
from nova.skills.router import SkillRouter


def test_performance_is_a_bounded_tie_breaker():
    assert performance_bonus(None) == 0.0 and performance_bonus(70.0) == 0.0
    assert performance_bonus(90.0) == 1.0 and performance_bonus(50.0) == -1.0
    assert performance_bonus(100.0) == MAX_BONUS and performance_bonus(0.0) == -MAX_BONUS  # never more than a nudge


def test_the_router_prefers_the_better_measured_skill_but_never_overrides_an_explicit_choice():
    router = SkillRouter(get_skill_registry())
    base = {c.skill.id: c.score for c in router.candidates("write a PRD for scheduled exports", limit=20)}
    top = max(base, key=base.get)
    runner_up = sorted(base, key=base.get, reverse=True)[1]
    gap = base[top] - base[runner_up]
    # A poorly measured top Skill and a well measured runner-up swap places only when the gap is within the nudge.
    scores = {top: 20.0, runner_up: 100.0}
    adjusted = {c.skill.id: c for c in router.candidates("write a PRD for scheduled exports", performance=scores, limit=20)}
    assert adjusted[top].score < base[top] and adjusted[runner_up].score > base[runner_up]
    assert any(r.startswith("FORGE score") for r in adjusted[runner_up].reasons)
    assert (adjusted[runner_up].score > adjusted[top].score) == (gap < 2 * MAX_BONUS)  # the most a nudge can change
    explicit = router.candidates("write a PRD", explicit=[top], performance={top: 0.0}, limit=20)
    assert explicit[0].skill.id == top and not any(r.startswith("FORGE score") for r in explicit[0].reasons)


def test_the_team_groups_skills_by_agent_with_their_measured_score():
    team = build_team(
        [("prd", "product"), ("vision-to-backlog", "product"), ("sprint-planning", "project")],
        {"prd": 80.0, "vision-to-backlog": 60.0},
    )
    assert [(m.agent, m.skills, m.score) for m in team] == [
        ("product", ["prd", "vision-to-backlog"], 70.0),
        ("project", ["sprint-planning"], None),
    ]
    assert build_team([("prd", "product"), ("prd", "product")], {})[0].skills == ["prd"]


def _state(classification: int):
    return SimpleNamespace(context_items=[SimpleNamespace(classification=classification)])


def test_secret_context_withholds_every_tool_that_writes_to_an_external_system():
    assert withholds_external_writes(3) and not withholds_external_writes(2)
    d = SimpleNamespace(tools=get_tool_registry())
    declared = ["search_orbit", "propose_orbit_decision", "publish_artifact_to_orbit", "get_artifact"]
    assert "propose_orbit_decision" in constrained_tools(d, _state(2), declared)  # C2: nothing withheld
    c3 = constrained_tools(d, _state(3), declared)
    assert "propose_orbit_decision" not in c3 and "publish_artifact_to_orbit" not in c3
    assert "search_orbit" in c3 and "get_artifact" in c3  # reading stays possible
