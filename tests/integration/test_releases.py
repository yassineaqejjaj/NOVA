"""Releases: canary exposure, verdicts, approval, rollback and the audit trail."""

from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from nova.config import get_settings
from nova.domain.agents import AgentProfile
from nova.domain.release import in_canary
from nova.infra import db
from nova.infra.models import AgentPolicy, AuditEvent, Release, Task
from nova.services import learning, releases
from nova.services.conversations import ComposerInput, create_conversation, submit
from nova.services.executions import run_task
from nova.skills.registry import get_skill_registry
from nova_api.main import create_app


async def _clean() -> None:
    """The test database is shared: leave no policy or release behind (training tests expect a fresh agent)."""
    async with db.session_scope() as session:
        for row in (await session.scalars(select(Release))).all():
            await session.delete(row)
        for row in (await session.scalars(select(AgentPolicy).where(AgentPolicy.agent == "product"))).all():
            await session.delete(row)
    learning.invalidate()


@pytest_asyncio.fixture(autouse=True)
async def release_settings(monkeypatch):
    await _clean()
    settings = get_settings()
    monkeypatch.setattr(settings, "release_canary_percent", 100)
    monkeypatch.setattr(settings, "release_canary_min_runs", 4)
    monkeypatch.setattr(settings, "release_max_failure_increase", 0.10)
    monkeypatch.setattr(settings, "release_approval", "full")
    yield
    await _clean()


async def _policies() -> tuple[uuid.UUID, uuid.UUID]:
    """An active base policy (v0) and a validated candidate (v1) for the product agent."""
    async with db.session_scope() as session:
        base = await learning.ensure_base_policy(session, AgentProfile.product)
        candidate = AgentPolicy(
            agent="product",
            version=await learning.next_version(session, AgentProfile.product),
            status="candidate",
            skills={"prd": ["Quantify every goal"]},
            score=82.0,
        )
        session.add(candidate)
        await session.flush()
        return base.id, candidate.id


async def _start(percent: int | None = None) -> Release:
    if percent is not None:
        get_settings().release_canary_percent = percent
    _, candidate_id = await _policies()
    async with db.session_scope() as session:
        candidate = await session.get(AgentPolicy, candidate_id)
        release = await releases.start(session, candidate, None, {"delta": 6.5, "experiment_id": "exp-1"})
        session.expunge(release)
        return release


async def _traffic(user, release_id, *, completed: int, failed: int, canary: bool) -> None:
    async with db.session_scope() as session:
        for i in range(completed + failed):
            session.add(
                Task(
                    user_id=uuid.UUID(user.user_id),
                    objective="x",
                    status="failed" if i < failed else "completed",
                    origin="interactive",
                    release_id=release_id if canary else None,
                )
            )


async def _reload(release_id) -> Release:
    async with db.session_scope() as session:
        return await session.get(Release, release_id)


async def _policy_status(policy_id) -> str:
    async with db.session_scope() as session:
        return (await session.get(AgentPolicy, policy_id)).status


async def test_canary_exposes_the_candidate_to_a_stable_share_only(user):
    release = await _start(percent=10)
    assert release.status == "canary" and release.baseline_policy_id is not None
    users = [str(uuid.uuid4()) for _ in range(300)]
    async with db.session_scope() as session:
        learned = {u: (await learning.snapshot(session, None, user_id=u))["product"] for u in users}
        again = {u: (await learning.snapshot(session, None, user_id=u))["product"] for u in users}
        anonymous = (await learning.snapshot(session))["product"]
    assert learned == again  # the same user always gets the same version
    inside = {u for u in users if learned[u].get("release_id")}
    assert inside == {u for u in users if in_canary(str(release.id), u, 10)}
    assert 0 < len(inside) < 60 and all(learned[u]["version"] == 1 for u in inside)
    assert all(learned[u]["version"] == 0 for u in users if u not in inside)
    assert anonymous["version"] == 0 and not anonymous.get("release_id")  # FORGE / replays never see the canary


async def test_a_degraded_canary_is_rolled_back_automatically(user):
    release = await _start()
    await _traffic(user, release.id, completed=2, failed=2, canary=True)
    await _traffic(user, release.id, completed=20, failed=0, canary=False)
    async with db.session_scope() as session:
        verdict = await releases.evaluate(session, await session.get(Release, release.id))
    assert verdict.outcome == "degraded"
    done = await _reload(release.id)
    assert done.status == "rolled_back" and "50%" in done.reason and done.decided_by == "system"
    assert await _policy_status(done.policy_id) == "rejected"
    async with db.session_scope() as session:
        assert (await learning.snapshot(session, None, user_id=user.user_id))["product"]["version"] == 0
        actions = set(await session.scalars(select(AuditEvent.action).where(AuditEvent.target_id == str(release.id))))
    assert {"release.canary_started", "release.rolled_back"} <= actions


async def test_a_healthy_canary_waits_for_approval_then_goes_live(user):
    release = await _start()
    await _traffic(user, release.id, completed=5, failed=0, canary=True)
    async with db.session_scope() as session:
        waiting = await releases.evaluate(session, await session.get(Release, release.id))
    assert waiting.outcome == "healthy"
    pending = await _reload(release.id)
    assert pending.status == "awaiting_approval" and "approbation" in pending.reason
    assert await _policy_status(pending.policy_id) == "candidate"  # not applied to everyone yet

    async with db.session_scope() as session:
        approved = await releases.approve(session, release.id, user.user_id)
    assert approved.status == "active" and approved.decided_by == user.user_id
    assert await _policy_status(approved.policy_id) == "active"
    async with db.session_scope() as session:
        assert (await learning.snapshot(session))["product"]["version"] == 1
        with pytest.raises(releases.ReleaseError):
            await releases.approve(session, release.id, user.user_id)  # nothing left to approve


async def test_without_approval_a_healthy_canary_goes_live_by_itself(user, monkeypatch):
    monkeypatch.setattr(get_settings(), "release_approval", "none")
    release = await _start()
    await _traffic(user, release.id, completed=5, failed=0, canary=True)
    async with db.session_scope() as session:
        await releases.evaluate(session, await session.get(Release, release.id))
    live = await _reload(release.id)
    assert live.status == "active" and live.decided_by == "system"


async def test_no_canary_and_no_approval_means_immediate_release(user, monkeypatch):
    monkeypatch.setattr(get_settings(), "release_approval", "none")
    release = await _start(percent=0)
    assert release.status == "active" and await _policy_status(release.policy_id) == "active"


async def test_an_active_release_can_be_rolled_back_to_its_baseline(user, monkeypatch):
    monkeypatch.setattr(get_settings(), "release_approval", "none")
    release = await _start(percent=0)
    base_id = release.baseline_policy_id
    async with db.session_scope() as session:
        undone = await releases.rollback(session, release.id, user.user_id, "Régression constatée")
    assert undone.status == "rolled_back" and undone.reason == "Régression constatée"
    assert await _policy_status(base_id) == "active" and await _policy_status(release.policy_id) == "rejected"
    async with db.session_scope() as session:
        assert (await learning.snapshot(session))["product"]["version"] == 0
        with pytest.raises(releases.ReleaseError):
            await releases.rollback(session, release.id, user.user_id)  # already withdrawn


async def test_a_newer_candidate_replaces_an_unfinished_release(user):
    first = await _start()
    second = await _start()
    assert (await _reload(first.id)).status == "rejected" and (await _reload(second.id)).status == "canary"
    assert await _policy_status(first.policy_id) == "rejected"


async def test_manual_activation_is_recorded_as_a_release(user):
    _, candidate_id = await _policies()
    async with db.session_scope() as session:
        release = await releases.activate_directly(session, await session.get(AgentPolicy, candidate_id), user.user_id)
        assert release.status == "active" and release.decided_by == user.user_id and release.canary_percent == 0


async def _ask(user, project) -> str:
    async with db.session_scope() as session:
        conversation = await create_conversation(session, user, project_id=project, title=None)
        _, _, task = await submit(
            session,
            user,
            conversation,
            ComposerInput(text="Create a PRD for scheduled CSV exports in FORGE", project_id=project),
            {s.id for s in get_skill_registry().all()},
        )
        return str(task.id)


async def test_a_run_in_the_canary_records_the_release_and_settling_it_triggers_the_verdict(user, project, llm, orbit, forge):
    get_settings().release_canary_min_runs = 1
    release = await _start()
    task_id = await _ask(user, project)
    assert await run_task(task_id, "start") == "completed"
    async with db.session_scope() as session:
        task = await session.get(Task, uuid.UUID(task_id))
        assert task.release_id == release.id
        assert task.run_manifest["release_id"] == str(release.id)
        assert task.run_manifest["policies"]["product"]["release_id"] == str(release.id)
        assert task.run_manifest["policies"]["product"]["version"] == 1
    # One healthy canary run was enough (min_runs=1): the release now waits for an administrator.
    assert (await _reload(release.id)).status == "awaiting_approval"


async def test_a_replay_never_counts_as_canary_traffic(user, project, llm, orbit, forge):
    release = await _start()
    task_id = await _ask(user, project)
    assert await run_task(task_id, "start") == "completed"
    async with db.session_scope() as session:
        from nova.domain.permissions import Principal
        from nova.services.replay import ReplayOptions, create_replay

        principal = Principal(user_id=user.user_id, email="x@example.com", display_name="Y")
        replay = await create_replay(session, principal, task_id, ReplayOptions())
        replay_id = str(replay.id)
    assert await run_task(replay_id, "start") == "completed"
    async with db.session_scope() as session:
        assert (await session.get(Task, uuid.UUID(replay_id))).release_id is None
    assert (await _reload(release.id)).status == "canary"


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


async def _client(app, *, admin: bool) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    body = {"email": email, "name": "Y", "title": "PM"}
    if admin:
        body["admin"] = True
    r = await client.post("/api/v1/auth/dev-login", json=body)
    assert r.status_code == 200, r.text
    return client


async def test_release_api_is_readable_by_all_and_decided_by_admins(app, user):
    release = await _start()
    await _traffic(user, release.id, completed=5, failed=0, canary=True)
    member = await _client(app, admin=False)
    listed = (await member.get("/api/v1/releases")).json()
    assert listed["can_manage"] is False and listed["releases"][0]["id"] == str(release.id)
    detail = (await member.get(f"/api/v1/releases/{release.id}")).json()
    assert detail["canary"]["runs"] == 5 and detail["control"]["runs"] == 0 and detail["status"] == "canary"
    for action in ("evaluate", "approve", "rollback"):
        assert (await member.post(f"/api/v1/releases/{release.id}/{action}")).status_code == 403
    assert (await member.get("/api/v1/releases/not-a-uuid")).status_code == 404


# --- Active releases are attributed too, and FORGE keeps watching them ------------------------------------


async def _live_release(monkeypatch) -> Release:
    """A release that already went live (no canary, no approval) with a previous release behind it."""
    monkeypatch.setattr(get_settings(), "release_approval", "none")
    first = await _start(percent=0)
    async with db.session_scope() as session:
        later = AgentPolicy(
            agent="product",
            version=await learning.next_version(session, AgentProfile.product),
            status="candidate",
            skills={"prd": ["Cite the rule"]},
        )
        session.add(later)
        await session.flush()
        second = await releases.start(session, later, None, {})
        assert second.status == "active" and str(second.baseline_policy_id) == str(first.policy_id)
        session.expunge(second)
        return second


async def test_an_active_release_is_attributed_to_the_runs_it_serves(user, monkeypatch):
    monkeypatch.setattr(get_settings(), "release_approval", "none")
    release = await _start(percent=0)  # goes live at once
    async with db.session_scope() as session:
        snapshot = await learning.snapshot(session, None, user_id=user.user_id)
    assert learning.release_of(snapshot) == str(release.id) and snapshot["product"]["canary"] is False


async def test_a_canary_user_is_attributed_to_the_canary_rather_than_the_active_release(user, monkeypatch):
    monkeypatch.setattr(get_settings(), "release_approval", "none")
    await _start(percent=0)  # active release
    canary = await _start(percent=100)  # everyone is in the canary of the next one
    async with db.session_scope() as session:
        snapshot = await learning.snapshot(session, None, user_id=user.user_id)
    assert snapshot["product"]["canary"] is True and learning.release_of(snapshot) == str(canary.id)


async def test_the_control_group_of_a_canary_includes_runs_served_by_the_active_release(user, monkeypatch):
    monkeypatch.setattr(get_settings(), "release_approval", "none")
    live = await _start(percent=0)
    canary = await _start(percent=100)
    await _traffic(user, canary.id, completed=3, failed=1, canary=True)
    await _traffic(user, live.id, completed=6, failed=2, canary=True)  # runs of the active release: not NULL
    async with db.session_scope() as session:
        canary_cohort, control = await releases.stats(session, await session.get(Release, canary.id))
    assert (canary_cohort.runs, canary_cohort.failed) == (4, 1)
    assert (control.runs, control.failed) == (8, 2)


class FakeForge:
    def __init__(self, health=None, error=None) -> None:
        self.health, self.error, self.calls = health or {}, error, []

    async def compare_releases(self, release_id, baseline_release_id, days=14):
        self.calls.append((release_id, baseline_release_id, days))
        if self.error:
            raise self.error
        return self.health


def _health(status, *kinds):
    return {
        "status": status,
        "reason": "r",
        "alerts": [{"kind": k, "message": f"alert {k}"} for k in kinds],
    }


async def _watch(client):
    async with db.session_scope() as session:
        return await releases.watch_active(session, client)


async def test_a_live_release_that_degrades_real_traffic_is_rolled_back_by_forge_health(user, monkeypatch):
    release = await _live_release(monkeypatch)
    forge = FakeForge(_health("degraded", "pass_rate_drop"))
    assert await _watch(forge) == [{"release_id": str(release.id), "status": "degraded", "rolled_back": True}]
    previous = await _reload(release.id)
    assert previous.status == "rolled_back" and previous.reason.startswith("FORGE : alert pass_rate_drop")
    assert await _policy_status(release.baseline_policy_id) == "active"
    # FORGE was asked about the release against the one it replaced.
    assert forge.calls[0][0] == str(release.id) and forge.calls[0][1] is not None
    async with db.session_scope() as session:  # back to the previous release's policy (v1), not the original v0
        assert (await learning.snapshot(session))["product"]["version"] == 1


async def test_healthy_or_inconclusive_verdicts_and_cost_alerts_never_roll_back(user, monkeypatch):
    release = await _live_release(monkeypatch)
    for health in (
        _health("healthy"),
        _health("insufficient_data"),
        _health("degraded", "cost_per_success_rise", "latency_p95_rise"),
    ):
        outcome = await _watch(FakeForge(health))
        assert outcome[0]["rolled_back"] is False
        assert (await _reload(release.id)).status == "active"
    kept = (await _reload(release.id)).evidence["health"]
    assert kept["status"] == "degraded" and kept["alerts"] == ["alert cost_per_success_rise", "alert latency_p95_rise"]


async def test_the_watch_can_be_switched_off_and_survives_forge_being_down(user, monkeypatch):
    release = await _live_release(monkeypatch)
    monkeypatch.setattr(get_settings(), "release_health_rollback", False)
    assert (await _watch(FakeForge(_health("degraded", "pass_rate_drop"))))[0]["rolled_back"] is False
    monkeypatch.setattr(get_settings(), "release_health_rollback", True)
    assert await _watch(FakeForge(error=RuntimeError("FORGE unreachable"))) == []
    assert (await _reload(release.id)).status == "active"


async def test_only_recently_activated_releases_are_watched(user, monkeypatch):
    release = await _live_release(monkeypatch)
    from datetime import timedelta

    async with db.session_scope() as session:
        row = await session.get(Release, release.id)
        row.decided_at = row.decided_at - timedelta(days=get_settings().release_watch_days + 1)
    forge = FakeForge(_health("degraded", "pass_rate_drop"))
    assert await _watch(forge) == [] and forge.calls == []


async def test_watch_without_a_configured_forge_does_nothing(user, monkeypatch):
    await _live_release(monkeypatch)
    monkeypatch.setattr(get_settings(), "forge_api_key", "")
    assert await releases.watch() == 0
