"""Release rules: stable canary buckets and the canary verdict."""

from __future__ import annotations

from nova.domain.release import Cohort, bucket, canary_verdict, in_canary


def test_a_user_always_lands_in_the_same_bucket_and_shares_are_roughly_respected():
    assert bucket("r1", "u1") == bucket("r1", "u1") and 0 <= bucket("r1", "u1") < 100
    users = [f"user-{i}" for i in range(2000)]
    share = sum(in_canary("r1", u, 10) for u in users) / len(users)
    assert 0.07 < share < 0.13
    assert not any(in_canary("r1", u, 0) for u in users[:200])
    assert all(in_canary("r1", u, 100) for u in users[:200])
    # Another release draws a different group: the same unlucky users are not always the canary.
    assert {u for u in users if in_canary("r1", u, 10)} != {u for u in users if in_canary("r2", u, 10)}


def test_the_verdict_waits_for_enough_runs():
    v = canary_verdict(Cohort(5, 5), Cohort(100, 0), min_runs=20, max_increase=0.1)
    assert v.outcome == "waiting" and "5/20" in v.reason


def test_a_clear_degradation_is_flagged_and_a_comparable_canary_is_healthy():
    bad = canary_verdict(Cohort(20, 6), Cohort(100, 5), min_runs=20, max_increase=0.1)
    assert bad.outcome == "degraded" and bad.canary_failure_rate == 0.3 and bad.control_failure_rate == 0.05
    ok = canary_verdict(Cohort(20, 2), Cohort(100, 5), min_runs=20, max_increase=0.1)
    assert ok.outcome == "healthy"
    better = canary_verdict(Cohort(20, 0), Cohort(100, 20), min_runs=20, max_increase=0.1)
    assert better.outcome == "healthy"
    assert canary_verdict(Cohort(20, 0), Cohort(0, 0), min_runs=20, max_increase=0.1).outcome == "healthy"
