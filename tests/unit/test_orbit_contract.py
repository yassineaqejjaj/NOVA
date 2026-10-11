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


def test_a_validated_learning_from_orbit_is_served_as_cited_untrusted_context():
    """ORION: ORBIT serves verified learnings as memory items of kind ``learning``; NOVA cites them like any
    source and wraps them as untrusted data (never as instructions)."""
    from nova.agent.prompts import context_block

    package = {
        "request_id": "r1",
        "items": [
            {
                "citation": "S2",
                "candidate_type": "memory",
                "id": "m1",
                "memory_item_id": "6a6a6a6a-0000-4000-8000-000000000001",
                "title": "Citer la règle métier",
                "memory_kind": "learning",
                "excerpt": "Quand une règle de remboursement est servie, la citer mot pour mot.",
                "classification": 1,
                "scores": {"final": 0.8},
                "reason_code": "INCLUDED",
            }
        ],
    }
    bundle = context_bundle(package, "atlas", "http://orbit")
    item = bundle.items[0]
    assert item.memory_kind == "learning" and item.citation == "S2" and item.kind == "memory"
    rendered = context_block(bundle.items)
    assert "memory/learning" in rendered and "S2" in rendered and "CONTEXT (cite with the label)" in rendered
