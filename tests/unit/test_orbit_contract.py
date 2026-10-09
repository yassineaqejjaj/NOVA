"""ORBIT's context package keeps evolving: unknown or richer fields must never break a retrieval."""

from __future__ import annotations

from nova.integrations.orbit.mapper import context_bundle
from nova.integrations.orbit.schemas import OrbitContextPackage


def test_structured_timings_from_a_newer_orbit_are_accepted():
    package = {
        "request_id": "req-1",
        "items": [],
        "timings": {"total": 42.5, "rounds": [{"round": 1, "queries": ["q"], "filtered": [], "ms": 270.6}]},
        "new_field": {"anything": True},
    }
    pkg = OrbitContextPackage.model_validate(package)
    assert context_bundle(pkg, "forge", "http://orbit").latency_ms == 42.5


def test_missing_or_non_numeric_total_gives_no_latency():
    for timings in ({}, {"total": "fast"}, {"rounds": []}):
        pkg = OrbitContextPackage.model_validate({"request_id": "r", "timings": timings})
        assert context_bundle(pkg, "forge", "http://orbit").latency_ms is None
