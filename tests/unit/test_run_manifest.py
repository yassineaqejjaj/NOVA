"""Run manifest: the ORION join key assembled from facts already known to an execution."""

from __future__ import annotations

from nova.domain.manifest import build_run_manifest, snapshot_id


def _manifest(**over):
    base = dict(
        run_id="t1",
        trace_id="abc",
        origin="interactive",
        agent_version="0.1.0",
        model="m",
        learning={"product": {"policy_id": "p1", "version": 3, "standards": ["x"]}},
        skills=[("prd", "1.2.0")],
        retrieval_id="req-9",
        snapshot_name="launch",
        snapshot_version=4,
        items=5,
        max_classification=2,
        token_budget=4000,
    )
    base.update(over)
    return build_run_manifest(**base)


def test_snapshot_id_uses_orbit_name_at_version_form():
    assert snapshot_id("launch", 4) == "launch@v4"
    assert snapshot_id("launch", None) == "launch@latest"
    assert snapshot_id(None, 4) is None


def test_manifest_gathers_agent_context_policy_and_skills():
    m = _manifest()
    assert m.context.snapshot_id == "launch@v4" and m.context.retrieval_id == "req-9"
    assert m.policies["product"].policy_id == "p1" and m.policies["product"].version == 3
    assert [(s.skill_id, s.version) for s in m.skills] == [("prd", "1.2.0")]
    assert (m.experiment_id, m.eval_suite_id, m.release_id) == (None, None, None)


def test_manifest_without_snapshot_or_policies():
    m = _manifest(snapshot_name=None, snapshot_version=None, learning={})
    assert m.context.snapshot_id is None and m.policies == {}


def test_later_phase_ids_are_accepted_and_unknown_keys_ignored():
    m = _manifest(ids={"experiment_id": "e1", "release_id": "r1", "bogus": "x"})
    assert m.experiment_id == "e1" and m.release_id == "r1"
    assert not hasattr(m, "bogus")


def test_forge_run_body_carries_the_production_manifest_and_snapshot_tag():
    from nova.domain.evaluation import ExecutionRecord
    from nova.integrations.forge.mapper import run_body

    manifest = _manifest().model_dump(mode="json")
    record = ExecutionRecord(
        task_id="t1",
        trace_id=None,
        user_intent="x",
        origin="interactive",
        agent_version="0.1.0",
        model="m",
        status="completed",
        manifest=manifest,
    )
    body = run_body("av-1", "sc-1", record)
    assert body["manifest"]["context"]["snapshot_id"] == "launch@v4"
    assert "context-snapshot:launch@v4" in body["tags"]
    assert "manifest" not in run_body("av-1", "sc-1", record.model_copy(update={"manifest": None}))
