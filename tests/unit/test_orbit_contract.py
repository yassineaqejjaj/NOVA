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


def test_package_snapshot_and_snapshot_endpoints_shapes():
    from nova.integrations.orbit.mapper import snapshot, snapshot_info

    pkg = {"request_id": "r", "snapshot": {"id": "i", "name": "plan", "version": 2}}
    assert context_bundle(pkg, "forge", "http://orbit").snapshot.version == 2
    assert context_bundle({"request_id": "r", "snapshot": None}, "forge", "http://orbit").snapshot is None
    assert snapshot_info({"name": "plan", "latest_version": 2, "versions": 2, "updated_at": None, "last_task": "t"}).versions == 2
    assert (
        snapshot({"name": "plan", "version": 2, "content": "c", "items": [], "request_id": "x", "content_hash": "h"}).version == 2
    )
