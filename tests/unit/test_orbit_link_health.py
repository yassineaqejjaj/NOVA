"""ORBIT link health: last exchange persisted, the switch to the project agent key signalled and audited, agents/self defensive."""

from __future__ import annotations

import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from nova.config import get_settings
from nova.domain.context import ContextError
from nova.infra import db
from nova.infra.db import utcnow
from nova.infra.models import AuditEvent, OrbitAccount
from nova.integrations.orbit.adapter import OrbitContextProvider
from nova.integrations.orbit.client import OrbitClient
from tests.conftest import scalar
from tests.support import fake_orbit_server as fake

AGENT_KEY = "orb_agent_key_for_tests_0123456789"


def _provider(transport: httpx.AsyncBaseTransport | None = None) -> OrbitContextProvider:
    return OrbitContextProvider(
        get_settings(), OrbitClient("http://orbit", transport=transport or httpx.ASGITransport(app=fake.app))
    )


async def _account(user) -> OrbitAccount:
    async with db.session_scope() as session:
        account = await session.get(OrbitAccount, uuid.UUID(user.user_id))
        session.expunge(account)
        return account


async def _expire(user) -> None:
    async with db.session_scope() as session:
        account = await session.get(OrbitAccount, uuid.UUID(user.user_id))
        account.expires_at = utcnow() - timedelta(minutes=5)


async def test_a_successful_exchange_is_remembered_with_no_error(user):
    provider = _provider()
    await provider.link_account(user.user_id, fake.USER["email"], fake.PASSWORD)
    await provider.list_projects(user.user_id)
    account = await _account(user)
    assert account.last_success_at is not None and account.last_error_at is None and account.last_error is None
    identity = await provider.identity(user.user_id)
    assert identity.last_success_at is not None and identity.last_error is None and not identity.fallback


async def test_a_failed_exchange_is_remembered_without_leaking_anything(user):
    provider = _provider()
    await provider.link_account(user.user_id, fake.USER["email"], fake.PASSWORD)
    with pytest.raises(ContextError):
        await provider.list_snapshots(user.user_id, "ghost-project")  # ORBIT answers 404
    identity = await provider.identity(user.user_id)
    assert identity.last_error_at is not None and "not_found" in (identity.last_error or "")
    assert "eyJ" not in (identity.last_error or "")  # never the token


async def test_an_expired_session_with_a_project_key_is_reported_as_the_agent_acting(user, monkeypatch):
    monkeypatch.setattr(get_settings(), "orbit_agent_keys", f"forge:{AGENT_KEY}")
    provider = _provider()
    await provider.link_account(user.user_id, fake.USER["email"], fake.PASSWORD)
    assert (await provider.identity(user.user_id)).fallback is False
    await _expire(user)

    identity = await provider.identity(user.user_id)
    assert identity.mode == "agent_key" and identity.fallback and identity.session_expired and not identity.linked
    assert identity.agent_projects == ["forge"]
    assert AGENT_KEY not in identity.model_dump_json()

    from nova.domain.context import ContextQuery

    query = ContextQuery(user_id=user.user_id, project_slug="forge", task="plan")
    await provider.retrieve(query)  # served through the project key
    await provider.retrieve(query)
    fallbacks = await scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.action == "orbit.agent_key_fallback", AuditEvent.actor_id == uuid.UUID(user.user_id))
    )
    assert fallbacks == 1  # logged once per switch, not once per call
    event = await scalar(select(AuditEvent).where(AuditEvent.action == "orbit.agent_key_fallback"))
    assert "forge" in event.summary and AGENT_KEY not in event.summary + str(event.details)

    await provider.link_account(user.user_id, fake.USER["email"], fake.PASSWORD)  # relinking ends the fallback
    assert (await provider.identity(user.user_id)).fallback is False


async def test_an_expired_session_without_a_key_is_just_expired(user, monkeypatch):
    monkeypatch.setattr(get_settings(), "orbit_agent_keys", "")
    provider = _provider()
    await provider.link_account(user.user_id, fake.USER["email"], fake.PASSWORD)
    await _expire(user)
    identity = await provider.identity(user.user_id)
    assert identity.session_expired and identity.mode == "none" and not identity.fallback
    with pytest.raises(ContextError) as exc:
        await provider.list_projects(user.user_id)
    assert exc.value.code == "unauthorized"
    assert "expired" in ((await provider.identity(user.user_id)).last_error or "")


def _agents_self(status: int, body: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/agents/self" and request.headers["x-orbit-key"] == AGENT_KEY
        return httpx.Response(status, json=body or {"detail": "x"})

    return httpx.MockTransport(handler)


@pytest.mark.parametrize(("status", "reason"), [(404, "unsupported"), (403, "forbidden"), (503, "unreachable")])
async def test_agents_self_unavailable_is_reported_never_raised(monkeypatch, status, reason):
    monkeypatch.setattr(get_settings(), "orbit_agent_keys", f"forge:{AGENT_KEY}")
    [state] = await _provider(_agents_self(status)).agent_keys_status()
    assert state == {"project": "forge", "available": False, "valid": None, "reason": reason}


async def test_agents_self_validates_the_key_and_exposes_only_its_scope(monkeypatch):
    monkeypatch.setattr(get_settings(), "orbit_agent_keys", f"forge:{AGENT_KEY}")
    body = {
        "name": "nova-forge",
        "project_slug": "forge",
        "clearance": 2,
        "scopes": ["context:read", "memory:write"],
        "api_key": "leak",
    }
    [state] = await _provider(_agents_self(200, body)).agent_keys_status()
    assert state == {
        "project": "forge",
        "available": True,
        "valid": True,
        "reason": None,
        "name": "nova-forge",
        "clearance": 2,
        "scopes": ["context:read", "memory:write"],
        "orbit_project": "forge",
    }
    [rejected] = await _provider(_agents_self(401)).agent_keys_status()
    assert rejected["available"] is True and rejected["valid"] is False and rejected["reason"] == "key_rejected"
