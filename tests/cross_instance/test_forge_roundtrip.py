"""NOVA against a REAL FORGE (not a fake): observed capture, evaluation, release comparison and rollback.

Skipped unless a FORGE is reachable::

    NOVA_E2E_FORGE_URL=http://127.0.0.1:8101 NOVA_E2E_FORGE_KEY=fgk_… uv run pytest tests/cross_instance -q

The FORGE needs its API *and* a worker (observed runs are evaluated by the ``evaluate_run`` job) and a key with the
admin role (the first capture creates the scenario and the rules-only evaluation config). Use a throwaway FORGE
database: this test writes agents, scenarios and runs into it.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid

import httpx
import pytest

from nova.config import get_settings
from nova.domain.agents import AgentProfile
from nova.infra import db
from nova.infra.models import AgentPolicy, Release, Task
from nova.integrations.forge.adapter import ForgeEvaluationSink
from nova.integrations.forge.client import ForgeClient
from nova.services import learning, providers, releases
from nova.services.conversations import ComposerInput, create_conversation, submit
from nova.services.executions import run_task
from nova.skills.registry import get_skill_registry

FORGE_URL = os.environ.get("NOVA_E2E_FORGE_URL", "")
FORGE_KEY = os.environ.get("NOVA_E2E_FORGE_KEY", "")

pytestmark = pytest.mark.skipif(not (FORGE_URL and FORGE_KEY), reason="needs NOVA_E2E_FORGE_URL and NOVA_E2E_FORGE_KEY")


@pytest.fixture
async def real_forge(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "forge_base_url", FORGE_URL)
    monkeypatch.setattr(settings, "forge_api_key", FORGE_KEY)
    monkeypatch.setattr(settings, "forge_capture_policy", "all")
    monkeypatch.setattr(settings, "forge_capture_mode", "observed")
    monkeypatch.setattr(settings, "release_approval", "none")
    monkeypatch.setattr(settings, "release_canary_percent", 0)
    client = ForgeClient(FORGE_URL, FORGE_KEY, timeout=30.0)
    sink = ForgeEvaluationSink(settings, get_skill_registry(), settings.llm_model, client=client)
    providers.override("evaluation", sink)
    providers.override("forge_client", client)
    yield client
    await client.aclose()


async def _ask(user, project) -> str:
    async with db.session_scope() as session:
        conversation = await create_conversation(session, user, project_id=project, title=None)
        _, _, task = await submit(
            session,
            user,
            conversation,
            ComposerInput(text=f"Create a PRD for scheduled CSV exports {uuid.uuid4().hex[:6]}", project_id=project),
            {s.id for s in get_skill_registry().all()},
        )
        return str(task.id)


async def _new_policy(version_note: str) -> AgentPolicy:
    async with db.session_scope() as session:
        await learning.ensure_base_policy(session, AgentProfile.product)
        policy = AgentPolicy(
            agent="product",
            version=await learning.next_version(session, AgentProfile.product),
            status="candidate",
            skills={"prd": [version_note]},
        )
        session.add(policy)
        await session.flush()
        session.expunge(policy)
        return policy


async def _go_live(policy: AgentPolicy) -> Release:
    async with db.session_scope() as session:
        release = await releases.start(session, await session.get(AgentPolicy, policy.id), None, {})
        assert release.status == "active"
        session.expunge(release)
        return release


async def _wait_for_runs(client: ForgeClient, release_id: str, expected: int, wait_seconds: float = 90.0) -> list[dict]:
    """Observed runs of a release that FORGE has finished evaluating."""
    async with httpx.AsyncClient(base_url=FORGE_URL, headers={"X-Forge-Key": FORGE_KEY}, timeout=30) as http:
        deadline = time.monotonic() + wait_seconds
        items: list[dict] = []
        while time.monotonic() < deadline:
            page = (await http.get("/api/v1/runs", params={"release_id": release_id, "page_size": 100})).json()
            items = page["items"]
            if len(items) >= expected and all(r["status"] in ("completed", "failed") for r in items):
                return items
            await asyncio.sleep(1.0)
    raise AssertionError(
        f"FORGE evaluated {sum(r['status'] in ('completed', 'failed') for r in items)}/{expected} runs of {release_id}"
    )


async def test_a_release_that_breaks_real_traffic_is_caught_by_a_real_forge_and_rolled_back(
    user, project, llm, orbit, real_forge
):
    first = await _go_live(await _new_policy("Quantify every goal"))
    healthy = [await _ask(user, project) for _ in range(12)]
    for task_id in healthy:
        assert await run_task(task_id, "start") == "completed"

    second = await _go_live(await _new_policy("Always answer in bullet points"))
    assert second.baseline_policy_id == first.policy_id
    async with db.session_scope() as session:
        user_row = await session.get(Task, uuid.UUID(healthy[0]))
        assert str(user_row.release_id) == str(first.id)  # the first release served the first runs
    # Under the second release every run fails (NOVA refuses to create Artifacts).
    from sqlalchemy import select

    from nova.infra.models import UserPreferences

    async with db.session_scope() as session:
        prefs = await session.scalar(select(UserPreferences).where(UserPreferences.user_id == uuid.UUID(user.user_id)))
        if prefs is None:
            prefs = UserPreferences(user_id=uuid.UUID(user.user_id))
            session.add(prefs)
        prefs.action_permissions = {"artifacts.create": "never"}
    broken = [await _ask(user, project) for _ in range(12)]
    for task_id in broken:
        assert await run_task(task_id, "start") == "failed"
    async with db.session_scope() as session:
        assert str((await session.get(Task, uuid.UUID(broken[0]))).release_id) == str(second.id)

    # What FORGE really received and scored.
    good_runs = await _wait_for_runs(real_forge, str(first.id), 12)
    bad_runs = await _wait_for_runs(real_forge, str(second.id), 12)
    assert all(r["origin"] == "observed" and r["passed"] for r in good_runs)
    assert all(r["status"] == "failed" and not r["passed"] for r in bad_runs)
    comparison = await real_forge.compare_releases(str(second.id), str(first.id), days=1)
    assert comparison["status"] == "degraded" and {a["kind"] for a in comparison["alerts"]} >= {"failure_rate_rise"}

    async with db.session_scope() as session:
        outcome = await releases.watch_active(session, real_forge)
    assert outcome == [{"release_id": str(second.id), "status": "degraded", "rolled_back": True}]
    async with db.session_scope() as session:
        rolled = await session.get(Release, second.id)
        assert rolled.status == "rolled_back" and rolled.reason.startswith("FORGE")
        assert (await session.get(AgentPolicy, first.policy_id)).status == "active"  # the previous policy is back
        assert (await learning.snapshot(session))["product"]["version"] == (
            await session.get(AgentPolicy, first.policy_id)
        ).version
