"""The improvement dashboard API: everyone reads it, and it only shows what NOVA measured."""

from __future__ import annotations

import uuid

import httpx
import pytest_asyncio
from sqlalchemy import select

from nova.infra import db
from nova.infra.models import AgentPolicy, Release, TrainingCycle
from nova_api.main import create_app


async def _clean() -> None:
    async with db.session_scope() as session:
        for model in (Release, TrainingCycle):
            for row in (await session.scalars(select(model))).all():
                await session.delete(row)
        for row in (await session.scalars(select(AgentPolicy).where(AgentPolicy.agent == "design"))).all():
            await session.delete(row)


@pytest_asyncio.fixture(autouse=True)
async def clean():
    await _clean()
    yield
    await _clean()


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


async def _client(app) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    r = await client.post(
        "/api/v1/auth/dev-login", json={"email": f"{uuid.uuid4().hex[:8]}@example.com", "name": "Y", "title": "PM"}
    )
    assert r.status_code == 200, r.text
    return client


async def test_progress_shows_the_curve_the_stopped_changes_and_no_invented_trend(app):
    async with db.session_scope() as session:
        base = AgentPolicy(agent="design", version=0, status="retired", score=None)
        better = AgentPolicy(agent="design", version=1, status="active", score=77.0, skills={"design-brief": ["Name the user"]})
        session.add_all([base, better])
        await session.flush()
        session.add(
            TrainingCycle(agent="design", status="promoted", baseline_policy_id=base.id, result={"baseline": {"mean": 66.0}})
        )
        session.add(TrainingCycle(agent="design", status="rejected", result={}))
        session.add(Release(agent="design", policy_id=better.id, label="design v2", status="rolled_back", reason="degraded"))

    member = await _client(app)
    body = (await member.get("/api/v1/training/progress")).json()
    design = next(a for a in body["agents"] if a["agent"] == "design")
    assert [p["score"] for p in design["curve"]] == [66.0, 77.0] and design["gain"] == 11.0
    assert design["changes_stopped"] == 2 and design["rollbacks"] == 1 and design["lessons"] == 1
    assert {"headline", "traffic", "window_days"} <= body.keys()
    assert body["headline"]["agents_measured"] >= 1
