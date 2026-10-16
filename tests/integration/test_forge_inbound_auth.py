"""FORGE -> NOVA authentication (ADR 001 §7, NOV-112): ``NOVA_FORGE_INBOUND_AUTH`` = token (default) | oidc | both.

The IdP is faked: tokens are RS256, signed by a throw-away key whose public half the (patched) JWKS client returns.
"""

from __future__ import annotations

import time

import httpx
import jwt
import pytest
import pytest_asyncio

from nova.config import get_settings
from nova.services import forge_inbound
from nova_api.main import create_app
from tests.contract.support import load_script

gen = load_script("generate_claims_fixtures")
ISSUER = gen.ISSUER
OTHER_ISSUER = "https://idp.orion.test/realms/nova"


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture(scope="module")
def key():
    return gen.new_key()


@pytest.fixture
def idp(key, monkeypatch):
    """The IdP's JWKS is the test key; NOVA expects the realm ``orion`` issuer for FORGE's service account."""
    settings = get_settings()
    monkeypatch.setattr(settings, "forge_inbound_issuer", ISSUER)
    monkeypatch.setattr(settings, "forge_inbound_clients", "forge-service")

    class Signing:
        def get_signing_key_from_jwt(self, token):
            return type("K", (), {"key": key.public_key()})()

    urls = []
    monkeypatch.setattr(forge_inbound, "_jwks_client", lambda url: urls.append(url) or Signing())
    return urls


def service_token(key, **overrides) -> str:
    now = int(time.time())
    payload = {
        "iss": ISSUER,
        "sub": gen.SERVICE_SUB,
        "aud": "nova-web",
        "azp": "forge-service",
        "preferred_username": "service-account-forge-service",
        "scope": "orion:run.execute",
        "iat": now,
        "exp": now + 300,
        **overrides,
    }
    return gen.sign_jwt(key, {k: v for k, v in payload.items() if v is not None})


async def call(app, token: str, *, prompt: str = "") -> httpx.Response:
    """An empty prompt answers 400 once authentication passed: the cheapest way to tell 'in' from 'out'."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(
            "/v1/agents/nova-orchestrator/runs",
            json={"input": {"prompt": prompt}, "agent": {}},
            headers={"Authorization": f"Bearer {token}".encode()},
        )


def is_in(response: httpx.Response) -> bool:
    return response.status_code != 401


def mode(monkeypatch, value: str) -> None:
    monkeypatch.setattr(get_settings(), "forge_inbound_auth", value)


# --- default: unchanged -----------------------------------------------------------------------------------------------


async def test_the_default_is_the_shared_bearer_and_nothing_else(app, idp, key):
    assert get_settings().forge_inbound_auth == "token"
    assert is_in(await call(app, get_settings().forge_inbound_token))
    refused = await call(app, service_token(key))  # a valid service-account token is not accepted in this mode
    assert refused.status_code == 401 and refused.json()["error"]["type"] == "UNAUTHORIZED"
    assert idp == []  # the IdP's keys were never even fetched
    assert (await call(app, "wrong")).status_code == 401


# --- oidc ------------------------------------------------------------------------------------------------------------


async def test_oidc_accepts_forges_service_account_and_refuses_the_shared_bearer(app, idp, key, monkeypatch):
    mode(monkeypatch, "oidc")
    assert is_in(await call(app, service_token(key)))
    assert (await call(app, get_settings().forge_inbound_token)).status_code == 401
    assert idp and idp[0].endswith("/realms/orion/protocol/openid-connect/certs")  # the keys of the configured issuer


async def test_oidc_runs_a_real_protocol_call(app, idp, key, monkeypatch):
    mode(monkeypatch, "oidc")
    response = await call(app, service_token(key), prompt="Write a PRD for the synthetic export feature.")
    assert response.status_code == 200 and response.json()["error"] is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "orbit"},
        {"aud": ["nova-web", "orbit"], "azp": "someone-else"},
        {"iss": OTHER_ISSUER},
        {"exp": int(time.time()) - 60, "iat": int(time.time()) - 400},
        {"scope": "orion:context.read"},
        {"scope": None},
        {"azp": "orbit"},
        {"azp": None},
        {"preferred_username": "alice@example.test"},  # a person, not a service account
        {"preferred_username": None},
        {"act": {"sub": "someone", "client_id": "nova-web"}},  # acting for someone
        {"orion_clearance": "3"},  # a malformed contract claim refuses the token
        {"sub": None},
    ],
    ids=lambda o: ",".join(f"{k}={v}" for k, v in o.items())[:60],
)
async def test_oidc_refuses_what_is_not_forges_service_account(app, idp, key, monkeypatch, overrides):
    mode(monkeypatch, "oidc")
    response = await call(app, service_token(key, **overrides))
    assert response.status_code == 401 and response.json()["error"]["message"] == "Jeton NOVA invalide"


async def test_oidc_refuses_forged_and_malformed_tokens(app, idp, key, monkeypatch):
    mode(monkeypatch, "oidc")
    other = gen.new_key()
    good = service_token(key)
    head, body, _ = good.split(".")
    for token in (
        service_token(other),  # signed by another key (the JWKS answers with the real one)
        f"{head}.{body}.",  # no signature
        jwt.encode({"iss": ISSUER, "aud": "nova-web", "sub": "x", "exp": int(time.time()) + 60}, "s" * 40, algorithm="HS256"),
        "a.b.c",
        "é.é.é",
        "x" * 3000,
    ):
        assert (await call(app, token)).status_code == 401


# --- both -----------------------------------------------------------------------------------------------------------


async def test_both_accepts_either_and_nothing_else(app, idp, key, monkeypatch):
    mode(monkeypatch, "both")
    assert is_in(await call(app, get_settings().forge_inbound_token))
    assert is_in(await call(app, service_token(key)))
    assert (await call(app, service_token(key, azp="other"))).status_code == 401
    assert (await call(app, "wrong")).status_code == 401


async def test_authorize_reports_the_method_and_compares_the_bearer_in_constant_time(idp, key, monkeypatch):
    settings = get_settings()
    mode(monkeypatch, "both")
    assert await forge_inbound.authorize(settings.forge_inbound_token, settings) == "token"
    assert await forge_inbound.authorize(service_token(key), settings) == "oidc"
    assert await forge_inbound.authorize("", settings) is None
    import inspect

    assert "compare_digest" in inspect.getsource(forge_inbound._shared_token)


def test_production_refuses_an_oidc_mode_without_a_client_and_keeps_the_dev_token_check(monkeypatch):
    from nova.config import DEV_FORGE_INBOUND_TOKEN, Settings

    base = {
        "env": "production",
        "session_secret": "s" * 40,
        "secrets_key": "k" * 40,
        "forge_inbound_token": "t" * 40,
        "cookie_secure": True,
        "public_url": "https://nova.test",
        "oidc_client_secret": "o" * 20,
        "auth_mode": "oidc",
    }
    Settings(**base)  # the default configuration is accepted, as before
    with pytest.raises(ValueError, match="NOVA_FORGE_INBOUND_TOKEN"):
        Settings(**{**base, "forge_inbound_token": DEV_FORGE_INBOUND_TOKEN})
    Settings(**{**base, "forge_inbound_token": DEV_FORGE_INBOUND_TOKEN, "forge_inbound_auth": "oidc"})  # no shared bearer needed
    with pytest.raises(ValueError, match="NOVA_FORGE_INBOUND_CLIENTS"):
        Settings(**{**base, "forge_inbound_auth": "both", "forge_inbound_clients": " , "})
