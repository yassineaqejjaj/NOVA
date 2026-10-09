"""Figma account endpoints (mocked Figma)."""

from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest_asyncio
from sqlalchemy import select

from nova.config import get_settings
from nova.infra.models import AuditEvent, FigmaAccount
from nova.integrations.figma.adapter import FigmaDesignProvider
from nova.services import providers
from nova_api.main import create_app
from tests.conftest import scalar


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


async def _client(app) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    r = await client.post(
        "/api/v1/auth/dev-login", json={"email": f"{uuid.uuid4().hex[:8]}@example.com", "name": "Y", "title": "UX"}
    )
    assert r.status_code == 200
    return client


def figma_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/me":
        if request.headers.get("x-figma-token") == "good-token-123":
            return httpx.Response(200, json={"id": "42", "handle": "Yass", "email": "y@x.io"})
        return httpx.Response(403, json={"err": "Invalid token"})
    if request.url.path == "/v1/oauth/token":
        return httpx.Response(200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600})
    return httpx.Response(404)


def use_provider(**settings) -> FigmaDesignProvider:
    provider = FigmaDesignProvider(get_settings().model_copy(update=settings), transport=httpx.MockTransport(figma_handler))
    providers.override("design", provider)
    return provider


async def test_status_token_link_and_unlink(app):
    use_provider()
    client = await _client(app)
    status = (await client.get("/api/v1/me/figma")).json()
    assert status == {
        "linked": False,
        "mode": None,
        "mcp": False,
        "can_write": False,
        "figma_handle": None,
        "oauth_available": False,
    }

    bad = await client.post("/api/v1/me/figma/token", json={"token": "wrong-token-123"})
    assert bad.status_code == 409 and bad.json()["code"] == "figma_token_invalid"

    ok = await client.post("/api/v1/me/figma/token", json={"token": "good-token-123"})
    assert ok.status_code == 200
    assert (
        ok.json()["linked"]
        and ok.json()["mode"] == "token"
        and not ok.json()["can_write"]
        and ok.json()["figma_handle"] == "Yass"
    )
    row = await scalar(select(FigmaAccount))
    assert row is not None and "good-token" not in (row.token_ciphertext or "")
    assert await scalar(select(AuditEvent).where(AuditEvent.action == "figma.link")) is not None

    assert (await client.delete("/api/v1/me/figma")).status_code == 204
    assert (await client.get("/api/v1/me/figma")).json()["linked"] is False
    assert await scalar(select(AuditEvent).where(AuditEvent.action == "figma.unlink")) is not None


async def test_connect_unavailable_without_client_id(app):
    use_provider()
    client = await _client(app)
    r = await client.post("/api/v1/me/figma/connect")
    assert r.status_code == 409 and r.json()["code"] == "figma_oauth_unavailable"


async def test_oauth_connect_and_callback(app):
    use_provider(figma_oauth_client_id="client-1")
    client = await _client(app)
    r = await client.post("/api/v1/me/figma/connect")
    assert r.status_code == 200
    query = parse_qs(urlsplit(r.json()["authorize_url"]).query)
    assert query["client_id"] == ["client-1"] and query["code_challenge_method"] == ["S256"]
    callback = await client.get("/api/v1/me/figma/callback", params={"code": "abc", "state": query["state"][0]})
    assert callback.status_code == 302 and callback.headers["location"].endswith("/settings?figma=connected")
    status = (await client.get("/api/v1/me/figma")).json()
    assert status["mode"] == "oauth" and status["mcp"] and status["can_write"]

    forged = await client.get("/api/v1/me/figma/callback", params={"code": "abc", "state": "forged"})
    assert forged.status_code == 400
