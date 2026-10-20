"""Nova Quality: the user's FORGE evaluations, summarised, and nobody else's."""

from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from nova.infra import db
from nova.infra.models import IntegrationReference, Task, User
from nova_api.main import create_app


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


async def _user(app) -> tuple[httpx.AsyncClient, uuid.UUID]:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post("/api/v1/auth/dev-login", json={"email": email, "name": "Q", "title": "PM"})
    assert r.status_code == 200, r.text
    async with db.session_scope() as session:
        user_id = await session.scalar(select(User.id).where(User.email == email))
    return client, user_id


async def _evaluated_task(user_id: uuid.UUID, objective: str, score: float, passed: bool) -> None:
    async with db.session_scope() as session:
        task = Task(user_id=user_id, objective=objective, status="completed", origin="interactive")
        session.add(task)
        await session.flush()
        session.add(
            IntegrationReference(
                system="forge",
                kind="evaluation",
                nova_type="task",
                nova_id=str(task.id),
                external_id=f"run-{uuid.uuid4().hex[:6]}",
                data={"composite_score": score, "passed": passed, "status": "completed", "url": "https://forge/runs/1"},
            )
        )


@pytest.mark.asyncio
async def test_overview_summarises_my_evaluations_only(app):
    me, my_id = await _user(app)
    _other, other_id = await _user(app)
    await _evaluated_task(my_id, "Write the PRD", 80, True)
    await _evaluated_task(my_id, "Plan the sprint", 60, False)
    await _evaluated_task(other_id, "Someone else's work", 10, False)

    body = (await me.get("/api/v1/quality")).json()

    assert body["summary"] == {"evaluated": 2, "average_score": 70.0, "pass_rate": 50}
    assert {e["objective"] for e in body["recent"]} == {"Write the PRD", "Plan the sprint"}
    assert "link" in body and "forge_url" in body


@pytest.mark.asyncio
async def test_overview_is_empty_without_evaluations(app):
    me, _ = await _user(app)
    body = (await me.get("/api/v1/quality")).json()
    assert body["summary"] == {"evaluated": 0, "average_score": None, "pass_rate": None}
    assert body["recent"] == []
