"""Improvement dashboard rules: the score curve, stopped changes and the failure-rate trend."""

from __future__ import annotations

from datetime import UTC, datetime

from nova.domain.improvement import CyclePoint, PolicyPoint, ReleasePoint, Traffic, agent_progress, headline, traffic_trend

T = datetime(2026, 9, 1, tzinfo=UTC)


def _policy(version: int, status: str, score: float | None, lessons: int = 0) -> PolicyPoint:
    return PolicyPoint(version, status, score, lessons, 1, T)


def test_the_curve_starts_from_the_first_measured_baseline_and_only_counts_live_versions():
    progress = agent_progress(
        [
            _policy(0, "retired", None),
            _policy(1, "retired", 71.2, 3),
            _policy(2, "active", 78.46, 5),
            _policy(3, "rejected", 90.0),
        ],
        [CyclePoint("promoted", 0, 64.0, T), CyclePoint("rejected", 2, 70.0, T)],
        [],
    )
    assert [p["version"] for p in progress["curve"]] == [0, 1, 2]
    assert progress["start_score"] == 64.0 and progress["current_score"] == 78.5 and progress["gain"] == 14.5
    assert progress["versions_shipped"] == 2 and progress["active_version"] == 2 and progress["lessons"] == 6


def test_an_agent_that_was_never_measured_has_an_empty_curve_not_a_flat_one():
    progress = agent_progress([_policy(0, "active", None)], [], [])
    assert progress["curve"] == [] and progress["gain"] is None and progress["current_score"] is None


def test_changes_that_never_reached_users_are_counted():
    progress = agent_progress(
        [],
        [CyclePoint("rejected", 0, None, T), CyclePoint("no_change", 0, None, T)],
        [ReleasePoint("rolled_back", "product v2", "failure rate 30%", T), ReleasePoint("active", "product v1", "", T)],
    )
    assert progress["changes_stopped"] == 2 and progress["rollbacks"] == 1
    assert progress["events"][0]["kind"] in {"rolled_back", "active"}


def test_the_trend_is_withheld_until_both_windows_hold_enough_runs():
    thin = traffic_trend(Traffic(3, 1), Traffic(40, 8))
    assert thin["comparable"] is False and thin["relative_change"] is None
    better = traffic_trend(Traffic(50, 5), Traffic(50, 10))
    assert better["comparable"] and better["relative_change"] == -0.5
    assert traffic_trend(Traffic(50, 0), Traffic(50, 0))["relative_change"] is None  # nothing to improve on


def test_the_headline_averages_only_measured_agents():
    a = {"gain": 10.0, "versions_shipped": 2, "lessons": 4, "changes_stopped": 1}
    b = {"gain": None, "versions_shipped": 0, "lessons": 0, "changes_stopped": 0}
    assert headline({"a": a, "b": b}) == {
        "mean_gain": 10.0,
        "versions_shipped": 2,
        "lessons_learned": 4,
        "changes_stopped": 1,
        "agents_measured": 1,
    }
