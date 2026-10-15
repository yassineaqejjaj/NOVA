"""Three separate indicators: execution health, deliverable quality, business gain (NOV-83)."""

from __future__ import annotations

from nova.domain.scores import BusinessSignals, DeliverableSignals, business_gain, deliverable_quality, execution_health


def test_execution_health_is_the_rule_score_forge_computes_on_observed_runs():
    assert execution_health(completed=True, all_skills_completed=True, error_count=0) == 100
    assert execution_health(completed=True, all_skills_completed=True, error_count=2) == round(500 / 6)  # weights 3 / 2 / 1
    assert execution_health(completed=False, all_skills_completed=False, error_count=1) == 0


def test_a_completed_run_with_an_empty_deliverable_and_broken_citations_is_healthy_but_poor():
    assert execution_health(completed=True, all_skills_completed=True, error_count=0) == 100
    poor = DeliverableSignals(artifacts=1, sections=6, empty_sections=6, validation=["passed"], dropped_citations=3)
    quality = deliverable_quality(poor)
    assert quality.score is not None and quality.score < 50
    checks = {c.key: c for c in quality.checks}
    assert checks["has_content"].value == 0 and checks["citations_resolved"].value == 0 and checks["validated"].value == 1


def test_a_run_that_delivered_nothing_scores_zero_for_content():
    quality = deliverable_quality(DeliverableSignals(artifacts=0))
    assert quality.score == 0 and [c.key for c in quality.checks] == ["has_content"]


def test_a_clean_validated_cited_deliverable_scores_full_marks():
    good = DeliverableSignals(artifacts=1, sections=6, empty_sections=0, validation=["passed"], dropped_citations=0, useful=True)
    assert deliverable_quality(good).score == 100


def test_a_revised_validation_counts_less_than_a_passed_one_and_a_warning_nothing():
    def score(status):
        return deliverable_quality(DeliverableSignals(artifacts=1, sections=2, empty_sections=0, validation=[status])).score

    assert score("passed") > score("revised") > score("warning")


def test_an_unhelpful_rating_lowers_the_quality_and_absent_signals_are_not_invented():
    base = DeliverableSignals(artifacts=1, sections=2, empty_sections=0)
    assert [c.key for c in deliverable_quality(base).checks] == ["has_content"]  # nothing else is known
    rated = deliverable_quality(base.model_copy(update={"useful": False}))
    assert rated.score is not None and rated.score < deliverable_quality(base).score  # type: ignore[operator]


def test_business_gain_needs_a_real_signal_and_follows_acceptance_and_corrections():
    assert business_gain(BusinessSignals()).score is None  # nothing collected: no number
    accepted = business_gain(BusinessSignals(accepted=True, versions=4, human_versions=0))
    corrected = business_gain(BusinessSignals(accepted=True, versions=4, human_versions=2))
    rejected = business_gain(BusinessSignals(accepted=False))
    assert accepted.score == 100 and corrected.score is not None and 50 < corrected.score < 100 and rejected.score == 0
