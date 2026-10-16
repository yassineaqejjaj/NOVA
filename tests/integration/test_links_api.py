"""Links screen API: ORBIT identity and health, ORBIT agent key state, FORGE link (admins), never a secret."""

from __future__ import annotations

import uuid
from datetime import timedelta

import httpx
import pytest_asyncio
from sqlalchemy import select

from nova.config import get_settings
from nova.infra import db
from nova.infra.db import utcnow
from nova.infra.models import OrbitAccount, User
from nova.integrations import link_health
from nova.integrations.orbit.adapter import OrbitContextProvider
from nova.integrations.orbit.client import OrbitClient
from nova.services import providers
from nova_api.main import create_app
from tests.support import fake_orbit_server as fake

API = "/api/v1"
AGENT_KEY = "orb_agent_key_for_tests_0123456789"
FORGE_KEY = "fgk_api_key_for_tests_0123456789"


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


async def login(app, *, admin: bool = False) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    assert (await client.post(f"{API}/auth/dev-login", json={"email": email, "name": "Y"})).status_code == 200
    if admin:
        async with db.session_scope() as session:
            (await session.scalar(select(User).where(User.email == email))).is_admin = True
    return client


def orbit_with(agents_self: int) -> None:
    """ORBIT double whose ``GET /agents/self`` answers ``agents_self`` (404: the endpoint does not exist yet)."""
    orbit = httpx.ASGITransport(app=fake.app)

    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/agents/self":
                body = {"name": "nova-forge", "project_slug": "forge", "clearance": 1, "scopes": ["context:read"]}
                return httpx.Response(agents_self, json=body)
            return await orbit.handle_async_request(request)

    providers.override("context", OrbitContextProvider(get_settings(), OrbitClient("http://orbit", transport=Transport())))


async def test_links_report_a_healthy_session_then_the_switch_to_the_project_key(app, monkeypatch):
    monkeypatch.setattr(get_settings(), "orbit_agent_keys", f"forge:{AGENT_KEY}")
    orbit_with(200)
    client = await login(app)
    assert (
        await client.post(f"{API}/me/orbit", json={"email": fake.USER["email"], "password": fake.PASSWORD})
    ).status_code == 200

    links = (await client.get(f"{API}/me/links")).json()
    orbit = links["orbit"]
    assert orbit["status"] == "ok" and orbit["mode"] == "session" and orbit["clearance"] == 2 and orbit["expires_at"]
    assert orbit["fallback"] is False and orbit["agent_keys"][0]["valid"] is True and orbit["agent_keys"][0]["clearance"] == 1
    assert orbit["agent_projects"] == ["forge"] and links["forge"] is None  # not an administrator

    me_view = (await client.get(f"{API}/me")).json()  # the same facts travel with /me
    me, me_id = me_view["orbit"], me_view["id"]
    assert me["mode"] == "session" and me["fallback"] is False

    async with db.session_scope() as session:  # the session runs out
        account = await session.get(OrbitAccount, uuid.UUID(me_id))
        account.expires_at = utcnow() - timedelta(minutes=1)
    expired = (await client.get(f"{API}/me/links")).json()["orbit"]
    assert (
        expired["status"] == "fallback" and expired["mode"] == "agent_key" and expired["fallback"] and expired["session_expired"]
    )
    assert AGENT_KEY not in (await client.get(f"{API}/me/links")).text


async def test_agents_self_missing_in_orbit_is_a_state_not_an_error(app, monkeypatch):
    monkeypatch.setattr(get_settings(), "orbit_agent_keys", f"forge:{AGENT_KEY}")
    orbit_with(404)
    client = await login(app)
    await client.post(f"{API}/me/orbit", json={"email": fake.USER["email"], "password": fake.PASSWORD})
    response = await client.get(f"{API}/me/links")
    assert response.status_code == 200
    assert response.json()["orbit"]["agent_keys"] == [
        {"project": "forge", "available": False, "valid": None, "reason": "unsupported"}
    ]


async def test_an_unlinked_user_still_gets_a_links_answer(app, monkeypatch):
    monkeypatch.setattr(get_settings(), "orbit_agent_keys", "")
    orbit_with(404)
    orbit = (await (await login(app)).get(f"{API}/me/links")).json()["orbit"]
    assert orbit["status"] == "unlinked" and orbit["agent_keys"] == []


async def test_the_forge_link_is_for_administrators_and_hides_every_secret(app, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "forge_api_key", FORGE_KEY)
    monkeypatch.setattr(settings, "forge_base_url", "https://user:pw@forge.example.com:8100/")
    monkeypatch.setattr(settings, "forge_credential_id", str(uuid.uuid4()))
    link_health.reset()
    await link_health.record_forge(error="HTTP 503")
    orbit_with(404)

    member = await login(app)
    assert (await member.get(f"{API}/me/links")).json()["forge"] is None
    admin = await login(app, admin=True)
    response = await admin.get(f"{API}/me/links")
    forge = response.json()["forge"]
    assert forge["configured"] and forge["api_key_present"] and forge["inbound_credential_set"]
    assert forge["endpoint"] == "https://forge.example.com:8100"  # resolved, with no userinfo
    assert forge["callback_endpoint"].startswith("http")
    assert forge["problems"] == [] or all("NOVA_FORGE" in p for p in forge["problems"])
    assert forge["status"] == "degraded" and forge["last_error"] == "HTTP 503" and forge["capture_queue"] is None
    for secret in (FORGE_KEY, "user:pw", settings.forge_credential_id):
        assert secret not in response.text

    await link_health.record_forge()  # a success after the error clears the degraded state
    assert (await admin.get(f"{API}/me/links")).json()["forge"]["status"] == "ok"

    monkeypatch.setattr(settings, "forge_api_key", "")
    assert (await admin.get(f"{API}/me/links")).json()["forge"]["status"] == "not_configured"
