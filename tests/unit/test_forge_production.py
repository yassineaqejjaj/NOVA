"""Production executions as FORGE observed runs: what is sent, and nothing more."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from nova.domain.evaluation import ExecutionRecord, SkillUse
from nova.domain.outputs import TokenUsage
from nova.integrations.forge import production

START = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)


def record(**over) -> ExecutionRecord:
    base = dict(
        task_id="t-1", trace_id="tr", user_intent="Create a PRD for CSV exports", origin="interactive", agent_version="0.1.0",
        model="m", workflow=["prd"], skills=[SkillUse(skill_id="prd", version="1.2.0", step_id="s1", status="completed", duration_ms=1200.0)],
        tools=["search_orbit"], artifact_ids=["a1"], output_markdown="SECRET ANSWER TEXT", usage=TokenUsage(input_tokens=900, output_tokens=300, model_calls=3),
        status="completed", errors=[], started_at=START, finished_at=START + timedelta(seconds=9),
        manifest={"run_id": "t-1", "release_id": "rel-1", "context": {"snapshot_id": "launch@v4"}},
        context_documents=[{"id": "S1", "title": "x", "content": "private excerpt", "source": "orbit"}],
    )  # fmt: skip
    base.update(over)
    return ExecutionRecord(**base)


def test_a_completed_run_reports_outcome_usage_manifest_and_steps_without_any_text():
    body = production.observed_run_body(record(), agent_version_id="av", scenario_id="sc", evaluation_config_id="cfg")
    assert body["external_id"] == "nova-task:t-1" and body["execution_status"] == "completed" and body["error"] is None
    assert body["output_json"] == {
        "outcome": "completed", "all_skills_completed": True, "error_count": 0,
        "skills": [{"skill_id": "prd", "version": "1.2.0", "status": "completed"}],
        "artifact_count": 1, "tools": ["search_orbit"], "context_items": 1, "context_max_classification": 0,
    }  # fmt: skip
    assert body["usage"] == {"input_tokens": 900, "output_tokens": 300, "model_calls": 3}
    assert body["started_at"] == START.isoformat() and body["completed_at"] == (START + timedelta(seconds=9)).isoformat()
    assert body["manifest"]["context"]["snapshot_id"] == "launch@v4" and "release:rel-1" in body["tags"]
    assert [e["type"] for e in body["events"]] == ["custom", "tool_call"] and body["events"][0]["duration_ms"] == 1200.0
    blob = str(body)
    assert "SECRET ANSWER TEXT" not in blob and "private excerpt" not in blob  # the answer and the context never leave
    assert "Create a PRD for CSV exports" not in blob  # nor, by default, what the user asked
    assert body["input"]["prompt"] == "[request text not sent] Skills: prd"


def test_a_failed_run_carries_its_errors_and_incomplete_skills():
    failed = record(
        status="failed",
        errors=["The model returned no usable content."],
        skills=[SkillUse(skill_id="prd", version="1.2.0", step_id="s1", status="incomplete")],
    )
    body = production.observed_run_body(failed, agent_version_id="av", scenario_id="sc")
    assert body["execution_status"] == "failed" and body["error"] == "The model returned no usable content."
    assert body["output_json"]["outcome"] == "failed" and body["output_json"]["all_skills_completed"] is False
    assert body["output_json"]["error_count"] == 1 and body["events"][0]["status"] == "error"
    assert body["evaluation_config_id"] is None and "manifest" in body


def test_the_scenario_rules_read_exactly_the_structured_result():
    paths = {r["params"]["path"] for r in production.scenario_body()["content"]["rules"]}
    assert paths <= set(production.observed_output(record())) and len(paths) == 3
    gate = production.evaluation_config_body()["gates"][0]
    assert gate["target"] == "completed" and gate["cap"] < 70  # an unfinished run can never pass


def test_the_request_text_is_sent_only_on_opt_in_and_then_redacted():
    secret = record(user_intent="Draft the contract for jane.doe@example.com, budget 1.2M")
    off = production.observed_run_body(secret, agent_version_id="av", scenario_id="sc")
    assert "jane.doe" not in str(off) and "contract" not in str(off)
    on = production.observed_run_body(secret, agent_version_id="av", scenario_id="sc", include_intent=True)
    assert "contract" in on["input"]["prompt"] and "jane.doe@example.com" not in on["input"]["prompt"]  # PII masked
