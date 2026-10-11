"""Adaptive context: the retrieval plan merges the candidate Skills' expected_context."""

from __future__ import annotations

from nova.domain.context_plan import MAX_TOKEN_BUDGET, plan_context
from nova.domain.skills import ExpectedContext


def _plan(candidates, budget=4000, purpose="general"):
    return plan_context(candidates, default_budget=budget, default_purpose=purpose)


def test_no_candidate_keeps_todays_behaviour():
    plan = _plan([], purpose="design")
    assert (plan.token_budget, plan.purpose, plan.source_kinds, plan.required) == (4000, "design", None, False)
    assert plan.augment("my request") == "my request"


def test_budget_is_the_largest_ask_and_never_below_the_default():
    big = ExpectedContext(token_budget=9000)
    small = ExpectedContext(token_budget=1000)
    assert _plan([small, big]).token_budget == 9000
    assert _plan([small]).token_budget == 4000
    assert _plan([ExpectedContext(token_budget=32000)], budget=40000).token_budget == MAX_TOKEN_BUDGET


def test_purpose_follows_candidates_only_when_they_agree():
    spec = ExpectedContext(orbit_intent="specification")
    assert _plan([spec, spec], purpose="research").purpose == "specification"
    assert _plan([spec, ExpectedContext(orbit_intent="design")], purpose="research").purpose == "research"
    assert _plan([ExpectedContext()], purpose="research").purpose == "research"  # "general" never overrides


def test_source_kinds_restrict_only_when_every_candidate_names_some():
    a = ExpectedContext(source_kinds=["ticket"])
    b = ExpectedContext(source_kinds=["document", "ticket"])
    assert _plan([a, b]).source_kinds == ["ticket", "document"]
    assert _plan([a, ExpectedContext()]).source_kinds is None


def test_hints_are_deduplicated_appended_and_bounded():
    hints = [
        ExpectedContext(query_hint="vision, goals"),
        ExpectedContext(query_hint="vision, goals"),
        ExpectedContext(query_hint="risks"),
    ]
    plan = _plan(hints)
    assert plan.query_hints == ["vision, goals", "risks"]
    assert plan.augment("Write a PRD") == "Write a PRD\n\nRelevant context: vision, goals risks"
    assert len(plan.augment("x" * 9000)) <= 7000
    assert _plan([ExpectedContext(required=True)]).required is True
