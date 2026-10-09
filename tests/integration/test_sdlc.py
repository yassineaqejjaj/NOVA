"""SDLC Autopilot end to end (fake GitHub, scripted model) and the bring-your-own-key settings."""

from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from nova.domain.sdlc import ChangeSet, FileChange, Finding, ReviewOutput
from nova.infra.models import AuditEvent, SdlcRun, UserLLMConfig
from nova.integrations.github.client import CheckSummary
from nova.services import providers
from nova.services.llm_config import provider_for_user
from nova_api.main import create_app
from tests.conftest import scalar
from tests.support.fake_github import FakeGitHub, SdlcLLM

API = "/api/v1"


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
def gh():
    fake = FakeGitHub()
    providers.override("github", lambda token: fake)
    return fake


@pytest.fixture
def model():
    fake = SdlcLLM()
    providers.override("llm", fake)
    return fake


async def login(app) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    r = await client.post(
        f"{API}/auth/dev-login", json={"email": f"{uuid.uuid4().hex[:8]}@example.com", "name": "Y", "title": "Dev"}
    )
    assert r.status_code == 200
    return client


async def linked(app) -> httpx.AsyncClient:
    client = await login(app)
    r = await client.put(f"{API}/me/github", json={"token": "ghp_" + "t" * 36})
    assert r.status_code == 200 and r.json()["login"] == "octo"
    return client


async def start(client, **body):
    payload = {"kind": "feature", "goal": "Add a farewell function next to greet", "repo": "o/r", **body}
    r = await client.post(f"{API}/sdlc/runs", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def stages(run) -> dict[str, str]:
    return {s["key"]: s["status"] for s in run["stages"]}


# --- Bring your own key ------------------------------------------------------------------------------------------------


async def test_user_llm_key_is_tested_encrypted_audited_and_used(app):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.headers.get("x-api-key") != "sk-ant-" + "k" * 30:
            return httpx.Response(401, json={"error": "invalid x-api-key"})
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "OK"}],
                "usage": {"input_tokens": 3, "output_tokens": 1},
                "model": "claude-sonnet-5-5",
            },
        )

    providers.override("llm_transport", httpx.MockTransport(handler))
    client = await login(app)
    key = "sk-ant-" + "k" * 30

    body = {"provider": "anthropic", "model": "claude-sonnet-5-5", "api_key": key}
    refused = await client.put(f"{API}/me/llm", json=body)
    assert refused.status_code == 422 and refused.json()["code"] == "llm_acknowledgement_required"

    bad = await client.put(f"{API}/me/llm", json={**body, "api_key": "sk-ant-" + "x" * 30, "acknowledge_data_sharing": True})
    assert bad.status_code == 422 and bad.json()["code"] == "llm_invalid"
    assert (await client.get(f"{API}/me/llm")).json()["configured"] is False

    ok = await client.put(f"{API}/me/llm", json={**body, "acknowledge_data_sharing": True})
    assert ok.status_code == 200
    data = ok.json()
    assert data["configured"] and data["provider"] == "anthropic" and data["key_hint"] == "kkkk"
    assert key not in ok.text and key not in (await client.get(f"{API}/me/llm")).text
    row = await scalar(select(UserLLMConfig))
    assert row is not None and key not in row.key_ciphertext
    assert await scalar(select(AuditEvent).where(AuditEvent.action == "llm.configure")) is not None
    assert {p["id"] for p in data["providers"]} >= {"anthropic", "openai", "google", "mistral", "openrouter", "custom"}

    assert (await client.post(f"{API}/me/llm/test")).json()["ok"] is True
    # Changing only the model keeps the stored key
    switched = await client.put(
        f"{API}/me/llm", json={"provider": "anthropic", "model": "claude-haiku-5-5", "acknowledge_data_sharing": True}
    )
    assert switched.status_code == 200 and switched.json()["model"] == "claude-haiku-5-5"

    me = (await client.get(f"{API}/me")).json()["id"]
    provider = await provider_for_user(me)
    assert provider is not None and provider.model_name == "claude-haiku-5-5"
    assert (await client.delete(f"{API}/me/llm")).status_code == 204
    assert await provider_for_user(me) is None


async def test_custom_endpoint_needs_a_url_and_a_key(app):
    client = await login(app)
    r = await client.put(
        f"{API}/me/llm", json={"provider": "custom", "model": "m", "api_key": "abc", "acknowledge_data_sharing": True}
    )
    assert r.status_code == 422 and "URL" in r.json()["detail"]
    r = await client.put(f"{API}/me/llm", json={"provider": "openai", "model": "gpt-5", "acknowledge_data_sharing": True})
    assert r.status_code == 422  # no key stored yet


# --- GitHub link ---------------------------------------------------------------------------------------------------------


async def test_github_link_repos_and_guards(app, gh, model):
    client = await login(app)
    assert (await client.get(f"{API}/me/github")).json()["linked"] is False
    no_token = await client.post(f"{API}/sdlc/runs", json={"goal": "Do something useful", "repo": "o/r"})
    assert no_token.status_code == 409 and no_token.json()["code"] == "github_unauthorized"
    await client.put(f"{API}/me/github", json={"token": "ghp_" + "t" * 36})
    assert (await client.get(f"{API}/me/github/repos")).json()[0]["full_name"] == "o/r"
    gh.can_push = False
    denied = await client.post(f"{API}/sdlc/runs", json={"goal": "Do something useful", "repo": "o/r"})
    assert denied.status_code == 403 and denied.json()["code"] == "github_forbidden"
    missing = await client.post(f"{API}/sdlc/runs", json={"goal": "Do something useful", "repo": "o/missing"})
    assert missing.status_code == 404
    assert (await client.delete(f"{API}/me/github")).status_code == 204


# --- The run -------------------------------------------------------------------------------------------------------------


async def test_guided_run_goes_from_intent_to_release_with_two_approvals(app, gh, model):
    client = await linked(app)
    run = await start(client)
    assert run["status"] == "waiting_user" and run["gate"] == "plan"
    assert stages(run)["spec"] == "done" and stages(run)["design"] == "done" and stages(run)["implement"] == "pending"
    assert gh.commits == [] and gh.prs == {}  # nothing written before the plan is approved

    run = (await client.post(f"{API}/sdlc/runs/{run['id']}/approve", json={"notes": "Keep it tiny"})).json()
    assert run["status"] == "waiting_user" and run["gate"] == "merge", run["error"]
    assert run["branch"].startswith("nova/feature-add-a-farewell") and run["pr_number"] == 1
    s = stages(run)
    assert [s[k] for k in ("implement", "tests", "pull_request", "review", "ci")] == ["done"] * 5 and s["merge"] == "waiting"
    assert any("Keep it tiny" in prompt for name, prompt in model.calls if name == "ChangeSet")
    assert [m for _, m, _ in gh.commits] == ["feat: add farewell", "test: cover farewell"]
    assert "farewell" not in gh.branches["main"]["src/greet.ts"]  # the default branch is untouched until the merge
    assert gh.comments and "NOVA review" in gh.comments[0][1]
    assert "Opened by" in gh.prs[1]["body"]

    run = (await client.post(f"{API}/sdlc/runs/{run['id']}/approve", json={})).json()
    assert run["status"] == "completed", run["error"]
    assert "farewell" in gh.branches["main"]["src/greet.ts"] and gh.deleted_branches == [run["branch"]]
    assert run["release"]["version"] == "v1.1.0" and run["usage"]["model_calls"] == 7
    assert run["merge_sha"]

    released = await client.post(f"{API}/sdlc/runs/{run['id']}/release", json={"tag": "v1.1.0"})
    assert released.status_code == 200 and released.json()["release_url"].endswith("v1.1.0")
    assert gh.releases[0]["draft"] is True and gh.releases[0]["target"] == run["merge_sha"]
    assert (await client.post(f"{API}/sdlc/runs/{run['id']}/deploy")).status_code == 409
    for action in ("sdlc.create", "sdlc.approve.plan", "sdlc.approve.merge", "sdlc.release"):
        assert await scalar(select(AuditEvent).where(AuditEvent.action == action)) is not None


async def test_autopilot_with_auto_merge_needs_no_human_when_everything_is_green(app, gh, model):
    client = await linked(app)
    run = await start(client, autonomy="autopilot", auto_merge=True)
    assert run["status"] == "completed", run["error"]
    assert all(v in ("done", "skipped") for v in stages(run).values())
    assert gh.prs[1]["merged"]


async def test_autopilot_still_asks_before_merging_by_default(app, gh, model):
    client = await linked(app)
    run = await start(client, autonomy="autopilot")
    assert run["status"] == "waiting_user" and run["gate"] == "merge"


async def test_blocking_review_findings_are_fixed_before_the_merge_gate(app, gh, model):
    model.review_queue = [
        ReviewOutput(
            verdict="request_changes",
            summary="Missing guard",
            findings=[
                Finding(
                    severity="blocker",
                    path="src/greet.ts",
                    line=4,
                    message="farewell mishandles empty names",
                    suggestion="guard it",
                )
            ],
        ),
        ReviewOutput(verdict="approve", summary="Fixed."),
    ]
    client = await linked(app)
    run = await start(client, autonomy="autopilot")
    review = next(s for s in run["stages"] if s["key"] == "review")
    assert [r["verdict"] for r in review["output"]["rounds"]] == ["request_changes", "approve"]
    assert "fix: address feedback" in [m for _, m, _ in gh.commits]
    assert run["status"] == "waiting_user" and run["gate"] == "merge"


async def test_ci_failure_is_repaired_then_goes_green(app, gh, model):
    failure = CheckSummary(
        state="failure",
        total=1,
        failures=[
            {
                "name": "test",
                "conclusion": "failure",
                "title": "1 failed",
                "summary": "farewell returned undefined",
                "annotations": [{"path": "src/greet.ts", "line": 4, "message": "bad"}],
            }
        ],
    )
    gh.check_script = [
        CheckSummary(state="none"),
        CheckSummary(state="pending", total=1, pending=["test"]),
        failure,
        CheckSummary(state="success", total=1),
    ]
    client = await linked(app)
    run = await start(client, autonomy="autopilot")
    assert run["status"] == "waiting_user" and run["gate"] == "merge", run["error"]
    ci = next(s for s in run["stages"] if s["key"] == "ci")
    assert ci["output"]["state"] == "success" and ci["output"]["fix_rounds"] == 1
    assert "fix: address feedback" in [m for _, m, _ in gh.commits]


async def test_ci_that_keeps_failing_stops_after_two_repairs_and_can_be_retried(app, gh, model):
    failing = CheckSummary(
        state="failure",
        total=1,
        failures=[{"name": "lint", "conclusion": "failure", "title": "", "summary": "", "annotations": []}],
    )
    gh.check_script = [failing]
    client = await linked(app)
    run = await start(client, autonomy="autopilot")
    assert run["status"] == "failed" and "lint" in run["error"] and stages(run)["ci"] == "failed"
    assert sum(1 for _, m, _ in gh.commits if m.startswith("fix")) == 2
    gh.check_script = [CheckSummary(state="success", total=1)]
    run = (await client.post(f"{API}/sdlc/runs/{run['id']}/retry")).json()
    assert run["status"] == "waiting_user" and run["gate"] == "merge"
    assert (await client.post(f"{API}/sdlc/runs/{run['id']}/retry")).status_code == 409


async def test_unsafe_generated_changes_never_reach_github(app, gh, model):
    bad = ChangeSet(
        summary="x",
        commit_message="x",
        changes=[FileChange(path=".github/workflows/ci.yml", action="create", content="on: push\n")],
    )
    model.change_queue = [bad, bad]
    client = await linked(app)
    run = await start(client, autonomy="autopilot")
    assert run["status"] == "failed" and "safe change set" in run["error"] and stages(run)["implement"] == "failed"
    assert gh.commits == [] and gh.prs == {}


async def test_bugfix_from_an_issue_closes_it_and_asks_for_root_cause(app, gh, model):
    client = await linked(app)
    run = await start(client, kind="bugfix", goal="", issue_url="https://github.com/o/r/issues/7", autonomy="autopilot")
    assert run["title"] == "Add farewell" and run["branch"].startswith("nova/bugfix-")
    assert "Closes #7" in gh.prs[1]["body"]
    spec_prompt = next(p for n, p in model.calls if n == "SpecOutput")
    assert "We need a farewell function" in spec_prompt and "<data" in spec_prompt


async def test_review_of_an_existing_pull_request_can_post_the_review(app, gh, model):
    model.review_queue = [
        ReviewOutput(
            verdict="request_changes", summary="Needs work", findings=[Finding(severity="major", path="a.py", message="bug")]
        )
    ]
    client = await linked(app)
    run = await start(client, kind="review", goal="", repo="", pr_url="https://github.com/o/r/pull/42", post_review=True)
    assert run["status"] == "completed" and run["pr_number"] == 42 and [s["key"] for s in run["stages"]] == ["review"]
    assert gh.reviews and "Needs work" in gh.reviews[0][1] and gh.commits == []
    quiet = await start(client, kind="review", goal="", repo="", pr_url="https://github.com/o/r/pull/43")
    assert quiet["status"] == "completed" and len(gh.reviews) == 1


async def test_cancel_and_ownership(app, gh, model):
    client = await linked(app)
    run = await start(client)
    other = await login(app)
    assert (await other.get(f"{API}/sdlc/runs/{run['id']}")).status_code == 404
    assert (await other.post(f"{API}/sdlc/runs/{run['id']}/approve", json={})).status_code == 404
    cancelled = (await client.post(f"{API}/sdlc/runs/{run['id']}/cancel")).json()
    assert cancelled["status"] == "cancelled"
    assert (await client.post(f"{API}/sdlc/runs/{run['id']}/approve", json={})).status_code == 409
    listed = (await client.get(f"{API}/sdlc/runs")).json()
    assert [r["id"] for r in listed] == [run["id"]] and "output" not in listed[0]["stages"][0]
    assert (await other.get(f"{API}/sdlc/runs")).json() == []


async def test_deploy_hook_is_stored_encrypted_and_only_called_after_the_merge(app, gh, model):
    calls: list[httpx.Request] = []
    providers.override("http_transport", httpx.MockTransport(lambda r: (calls.append(r), httpx.Response(200))[1]))
    client = await linked(app)
    run = await start(client, autonomy="autopilot", auto_merge=True, deploy_hook="http://deploy.example.com/hook/secret-token")
    assert run["has_deploy_hook"] and "secret-token" not in str(run)
    row = await scalar(select(SdlcRun).where(SdlcRun.id == uuid.UUID(run["id"])))
    assert row is not None and "secret-token" not in (row.deploy_hook_ciphertext or "")
    assert (await client.post(f"{API}/sdlc/runs/{run['id']}/deploy")).status_code == 200
    assert calls and calls[0].url.host == "deploy.example.com"
