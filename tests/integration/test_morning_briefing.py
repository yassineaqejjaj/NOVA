"""The morning inbox: engineering runs waiting for a decision, and Artifacts whose sources changed."""

from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio

from nova.domain.sdlc import STAGES
from nova.infra import db
from nova.infra.models import SdlcRun, User
from nova.services import freshness
from nova_api.main import create_app
from tests.integration.test_freshness import _artifact, _change


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture(autouse=True)
def _clean_memory():
    freshness.forget()
    yield
    freshness.forget()


async def _client(app) -> tuple[httpx.AsyncClient, uuid.UUID]:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post("/api/v1/auth/dev-login", json={"email": email, "name": "Y", "title": "PM"})
    assert r.status_code == 200, r.text
    async with db.session_scope() as session:
        from sqlalchemy import select

        user_id = await session.scalar(select(User.id).where(User.email == email))
    return client, user_id


async def _run(user_id: uuid.UUID, *, gate: str | None, status: str = "waiting_user", preview: str | None = None) -> SdlcRun:
    stages = [{"key": k, "status": "done", "summary": "", "output": {}} for k in STAGES]
    run = SdlcRun(
        user_id=user_id,
        title="Add a farewell function",
        repo="o/r",
        base_branch="main",
        status=status,
        stage="merge" if gate == "merge" else "design",
        gate=gate,
        stages=stages,
        pr_number=12 if gate == "merge" else None,
        pr_url="https://github.com/o/r/pull/12" if gate == "merge" else "",
        context={"preview_url": preview} if preview else {},
    )
    async with db.session_scope() as session:
        session.add(run)
        await session.flush()
        session.expunge(run)
    return run


def _ids(today: dict) -> list[str]:
    return [item["id"] for item in today["inbox"]["items"]]


async def test_runs_waiting_at_a_gate_reach_the_morning_inbox_with_their_preview(app):
    client, uid = await _client(app)
    plan = await _run(uid, gate="plan")
    merge = await _run(uid, gate="merge", preview="https://nova-pr-12.vercel.app")
    await _run(uid, gate=None, status="running")  # not waiting: stays out

    today = (await client.get("/api/v1/today")).json()
    items = {i["id"]: i for i in today["inbox"]["items"]}
    assert f"sdlc:plan:{plan.id}" in items and f"sdlc:merge:{merge.id}" in items
    merge_item = items[f"sdlc:merge:{merge.id}"]
    assert merge_item["kind"] == "decision" and merge_item["urgent"] is True
    assert "https://nova-pr-12.vercel.app" in merge_item["subtitle"] and "#12" in merge_item["title"]
    assert merge_item["actions"][0]["href"] == f"/engineering/{merge.id}"
    assert today["brief"]["actions_required"] >= 2


async def test_runs_of_other_people_never_show_up(app):
    mine, _ = await _client(app)
    _, other_id = await _client(app)
    foreign = await _run(other_id, gate="merge")
    today = (await mine.get("/api/v1/today")).json()
    assert f"sdlc:merge:{foreign.id}" not in _ids(today)


async def test_an_artifact_whose_sources_changed_is_flagged_in_the_morning_inbox(app, llm, orbit, forge):
    client, _ = await _client(app)
    artifact_id = await _artifact(client, llm)

    calm = (await client.get("/api/v1/today")).json()
    assert not [i for i in _ids(calm) if i.startswith("artifact:stale:")]

    freshness.forget()
    orbit.changes = [_change("chunk-1")]
    today = (await client.get("/api/v1/today")).json()
    stale = [i for i in today["inbox"]["items"] if i["id"].startswith("artifact:stale:")]
    assert len(stale) == 1 and stale[0]["artifact_id"] == artifact_id
    assert stale[0]["kind"] == "anomaly" and stale[0]["actions"][0]["href"] == f"/artifacts/{artifact_id}"
    assert "Q4 goals were revised" in stale[0]["subtitle"]


async def test_an_unreachable_orbit_is_not_remembered_and_never_breaks_the_page(app, llm, orbit, forge):
    from nova.domain.context import ContextError

    client, _ = await _client(app)
    await _artifact(client, llm)

    async def down(*_args, **_kwargs):
        raise ContextError("unavailable", "ORBIT is down")

    original = orbit.recent_changes
    orbit.recent_changes = down
    today = await client.get("/api/v1/today")
    assert today.status_code == 200 and not [i for i in _ids(today.json()) if i.startswith("artifact:stale:")]

    orbit.recent_changes = original
    orbit.changes = [_change("chunk-1")]
    again = (await client.get("/api/v1/today")).json()  # ORBIT is back: asked again, not served from memory
    assert [i for i in _ids(again) if i.startswith("artifact:stale:")]
