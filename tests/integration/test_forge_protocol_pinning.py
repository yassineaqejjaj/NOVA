"""FORGE protocol: which version ran, the budgets received, overrides refused, any bad token is a 401 (synthetic data)."""

from __future__ import annotations

import uuid

import httpx
import pytest_asyncio
from sqlalchemy import func, select

from nova.config import get_settings
from nova.domain.agents import AgentProfile, agent_instructions
from nova.infra import db
from nova.infra.models import LLMCall, Task
from nova.integrations.forge import mapper
from nova.services import learning, providers
from nova.skills.registry import get_skill_registry
from nova_api.main import create_app


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


def current_label() -> str:
    """The version label a FORGE agent version registered by this NOVA carries."""
    settings = get_settings()
    return mapper.release_label(
        settings.version, providers.llm().model_name, get_skill_registry().catalog_digest(), settings.llm_provider
    )


async def post(app, agent: dict | None = None, *, agent_id="nova-orchestrator", budget=None, options=None, token=None):
    body = {"input": {"prompt": "Write a PRD for the synthetic export feature."}, "agent": agent or {}}
    if budget:
        body["budget"] = budget
    if options:
        body["options"] = options
    headers = {"Authorization": f"Bearer {token or get_settings().forge_inbound_token}".encode()}  # raw bytes: UTF-8 on the wire
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as forge:
        return await forge.post(f"/v1/agents/{agent_id}/runs", json=body, headers=headers)


async def forge_tasks() -> int:
    async with db.session_scope() as session:
        return await session.scalar(select(func.count()).select_from(Task).where(Task.origin == "forge_protocol"))


# --- Token -------------------------------------------------------------------------------------------------------------


async def test_a_bearer_token_with_non_ascii_characters_is_a_401_not_a_500(app):
    for token in ("jeton-é", "令牌", "tok en"):
        response = await post(app, token=token)
        assert response.status_code == 401 and response.json()["error"]["type"] == "UNAUTHORIZED"


# --- Version declared, executed, overrides -----------------------------------------------------------------------------


async def test_the_response_tells_the_declared_version_apart_from_the_executed_one(app):
    response = await post(app, {"version": current_label(), "slug": "nova"}, options={})
    data = response.json()
    assert response.status_code == 200 and data.get("error") is None
    meta = data["metadata"]
    assert meta["requested_version"] == current_label()
    assert meta["executed_version"] and meta["executed_version"] != meta["requested_version"]
    executed = meta["executed"]
    assert executed["nova_version"] == get_settings().version and executed["skill_catalog"] == meta["skill_catalog"]
    assert executed["provider"] == get_settings().llm_provider and executed["model"] == providers.llm().model_name
    assert executed["policy_id"] is None and "runtime_commit" in executed
    assert meta["executed_version"] == (await post(app, {"version": current_label()})).json()["metadata"]["executed_version"]


async def test_no_declared_version_is_reported_as_such(app):
    meta = (await post(app)).json()["metadata"]
    assert meta["requested_version"] is None and meta["executed_version"]


async def test_a_run_pinned_to_an_older_release_is_refused_not_run_on_the_current_one(app):
    old = current_label()
    get_settings().version = "9.9.9"  # NOVA was released again since FORGE registered that version
    try:
        before = await forge_tasks()
        response = await post(app, {"version": old})
    finally:
        get_settings().version = "0.1.0"
    data = response.json()
    assert response.status_code == 422 and data["error"]["type"] == "unsupported_override"
    assert data["error"]["fields"] == ["agent.version"] and old in data["error"]["message"]
    assert await forge_tasks() == before  # nothing ran


async def test_a_model_or_prompt_or_tools_other_than_the_runtime_are_refused_with_their_names(app):
    runtime_model = providers.llm().model_name
    response = await post(
        app,
        {
            "model": {"provider": "openai", "model": "gpt-other"},
            "system_prompt": "You are another agent.",
            "tools": [{"name": "jira.search"}],
        },
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["type"] == "unsupported_override" and error["retryable"] is False
    assert error["fields"] == ["agent.model", "agent.system_prompt", "agent.tools"]
    assert "gpt-other" in error["message"] and runtime_model in error["message"]


async def test_the_runtime_model_and_an_empty_prompt_are_accepted(app):
    same = {"provider": get_settings().llm_provider, "model": providers.llm().model_name}
    response = await post(app, {"model": same, "system_prompt": "", "tools": [], "version": current_label()})
    assert response.status_code == 200 and response.json().get("error") is None


async def test_a_specialist_version_is_checked_against_its_policy(app):
    async with db.session_scope() as session:
        policy = await learning.ensure_base_policy(session, AgentProfile.product)
        policy_id, version, standards = str(policy.id), policy.version, list(policy.standards)
    options = {"policy_id": policy_id}
    ok = await post(
        app,
        {"version": f"{version}.1a2b3c4d", "system_prompt": agent_instructions(AgentProfile.product, standards)},
        agent_id="nova-product",
        options=options,
    )
    assert ok.status_code == 200, ok.text
    meta = ok.json()["metadata"]
    assert meta["executed"]["policy_id"] == policy_id and "options.policy_id" in meta["accepted_overrides"]
    stale = await post(app, {"version": f"{version + 1}.1a2b3c4d"}, agent_id="nova-product", options=options)
    assert stale.status_code == 422 and stale.json()["error"]["fields"] == ["agent.version"]
    foreign = await post(app, {"system_prompt": "Do something else."}, agent_id="nova-product", options=options)
    assert foreign.status_code == 422 and foreign.json()["error"]["fields"] == ["agent.system_prompt"]


# --- Budgets ------------------------------------------------------------------------------------------------------------


async def test_a_low_token_budget_from_forge_interrupts_the_run(app, monkeypatch):
    assert get_settings().run_token_budget == 0  # NOVA itself sets no cap here
    response = await post(app, budget={"max_tokens": 1, "timeout_seconds": 60})
    data = response.json()
    assert data["error"]["type"] == "EXECUTION_ERROR" and "limit of 1 tokens" in data["error"]["message"]
    async with db.session_scope() as session:
        task = await session.scalar(select(Task).where(Task.id == uuid.UUID(data["metadata"]["nova_task_id"])))
        calls = (await session.scalars(select(LLMCall).where(LLMCall.task_id == task.id))).all()
    assert len(calls) == 1  # the first call went through, the second was refused
    assert data["metadata"]["executed"]["parameters"]["max_tokens"] == 1
    assert "budget.max_tokens" in data["metadata"]["accepted_overrides"]


async def test_the_tighter_of_forge_and_nova_budgets_applies(app, monkeypatch):
    monkeypatch.setattr(get_settings(), "run_token_budget", 1)  # NOVA's own cap is lower than FORGE's
    data = (await post(app, budget={"max_tokens": 1_000_000})).json()
    assert "limit of 1 tokens" in data["error"]["message"]
    assert data["metadata"]["executed"]["parameters"]["max_tokens"] == 1


async def test_a_cost_budget_from_forge_interrupts_the_run_once_prices_make_calls_cost(app, monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_price_input_per_mtok", 1_000_000.0)  # every token costs $1
    data = (await post(app, budget={"max_cost": 5.0})).json()
    assert "cost limit ($5)" in data["error"]["message"]


async def test_a_generous_budget_changes_nothing(app):
    data = (await post(app, budget={"max_tokens": 10_000_000, "max_cost": 1000.0, "max_steps": 8})).json()
    assert data.get("error") is None
