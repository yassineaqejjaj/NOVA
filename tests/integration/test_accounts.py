"""Accounts: sign-up restricted to the company domain and confirmed by an e-mailed code, password sign-in, reset."""

from __future__ import annotations

import uuid

import httpx
import pytest_asyncio

from nova.services import mailer
from nova_api.main import create_app

PASSWORD = "Orbit-and-forge-2026"


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


def _anonymous(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _address() -> str:
    return f"camille.{uuid.uuid4().hex[:6]}@devoteam.com"


async def _code(client: httpx.AsyncClient, email: str) -> str:
    code = (await client.get("/api/v1/auth/dev/outbox", params={"email": email})).json()["code"]
    assert code and len(code) == 6
    return code


async def test_signup_requires_a_devoteam_address_terms_and_a_strong_password(app):
    client = _anonymous(app)
    config = (await client.get("/api/v1/auth/config")).json()
    assert config["signup"] == {"enabled": True, "domains": ["devoteam.com"]}
    assert config["providers"] == [{"id": "google", "name": "Google", "available": False}]

    base = {"name": "Camille Martin", "password": PASSWORD, "accept_terms": True}
    for email in ("camille@gmail.com", "camille@devoteam.com.evil.io", "camille@sub.devoteam.com"):
        response = await client.post("/api/v1/auth/signup", json={**base, "email": email})
        assert response.status_code == 422 and response.json()["code"] == "domain_not_allowed", email
    weak = await client.post("/api/v1/auth/signup", json={**base, "email": _address(), "password": "short1"})
    assert weak.json()["code"] == "weak_password"
    terms = await client.post("/api/v1/auth/signup", json={**base, "email": _address(), "accept_terms": False})
    assert terms.json()["code"] == "terms_required"


async def test_signup_is_activated_by_the_emailed_code_then_password_sign_in_works(app):
    client = _anonymous(app)
    email = _address()
    response = await client.post(
        "/api/v1/auth/signup",
        json={"email": email.upper(), "name": "Camille Martin", "password": PASSWORD, "accept_terms": True, "lang": "fr"},
    )
    assert response.status_code == 202, response.text
    sent = mailer.OUTBOX[-1]
    assert sent.to == email and "code de vérification" in sent.subject and sent.code not in (None, "")

    # Not usable before the address is confirmed
    early = await client.post("/api/v1/auth/password-login", json={"email": email, "password": PASSWORD})
    assert early.status_code == 403 and early.json()["code"] == "email_not_verified"
    # A new code cannot be requested right away (resend throttling)
    assert (await client.post("/api/v1/auth/signup/resend", json={"email": email})).json()["code"] == "too_many_requests"

    wrong = await client.post("/api/v1/auth/signup/verify", json={"email": email, "code": "000000"})
    assert wrong.json()["code"] in ("invalid_code",) or (await _code(client, email)) == "000000"
    verified = await client.post("/api/v1/auth/signup/verify", json={"email": email, "code": await _code(client, email)})
    assert verified.status_code == 200, verified.text
    assert "max-age" not in verified.headers["set-cookie"].lower()  # browser-session cookie
    me = (await client.get("/api/v1/me")).json()
    assert me["email"] == email and me["display_name"] == "Camille Martin"
    assert me["preferences"]["onboarding_completed"] is False  # onboarding comes next

    # The code is single-use; the account now exists
    again = await client.post("/api/v1/auth/signup/verify", json={"email": email, "code": await _code(client, email)})
    assert again.json()["code"] == "code_expired"
    exists = await client.post(
        "/api/v1/auth/signup", json={"email": email, "name": "X", "password": PASSWORD, "accept_terms": True}
    )
    assert exists.status_code == 409 and exists.json()["code"] == "account_exists"

    other = _anonymous(app)
    bad = await other.post("/api/v1/auth/password-login", json={"email": email, "password": "Wrong-password-1"})
    assert bad.status_code == 401 and bad.json()["code"] == "invalid_credentials"
    ok = await other.post("/api/v1/auth/password-login", json={"email": email, "password": PASSWORD, "remember": True})
    assert ok.status_code == 200 and "max-age=2592000" in ok.headers["set-cookie"].lower()  # kept signed in 30 days
    assert (await other.get("/api/v1/me")).json()["email"] == email


async def test_codes_expire_after_too_many_attempts(app):
    client = _anonymous(app)
    email = _address()
    await client.post("/api/v1/auth/signup", json={"email": email, "name": "C M", "password": PASSWORD, "accept_terms": True})
    real = await _code(client, email)
    wrong = "111111" if real != "111111" else "222222"
    for _ in range(5):
        await client.post("/api/v1/auth/signup/verify", json={"email": email, "code": wrong})
    blocked = await client.post("/api/v1/auth/signup/verify", json={"email": email, "code": real})
    assert blocked.json()["code"] == "code_expired"


async def test_password_reset_by_code_without_revealing_unknown_addresses(app):
    client = _anonymous(app)
    email = _address()
    await client.post("/api/v1/auth/signup", json={"email": email, "name": "C M", "password": PASSWORD, "accept_terms": True})
    await client.post("/api/v1/auth/signup/verify", json={"email": email, "code": await _code(client, email)})

    unknown = await client.post("/api/v1/auth/password/forgot", json={"email": "nobody@devoteam.com"})
    known = await client.post("/api/v1/auth/password/forgot", json={"email": email, "lang": "fr"})
    assert unknown.status_code == known.status_code == 202 and unknown.json() == known.json()
    assert (await client.get("/api/v1/auth/dev/outbox", params={"email": "nobody@devoteam.com"})).json()["code"] is None
    assert "Réinitialisation" in mailer.OUTBOX[-1].subject

    new_password = "A-brand-new-password-7"
    reset = await client.post(
        "/api/v1/auth/password/reset", json={"email": email, "code": await _code(client, email), "password": new_password}
    )
    assert reset.status_code == 200, reset.text
    assert (await client.post("/api/v1/auth/password-login", json={"email": email, "password": PASSWORD})).status_code == 401
    assert (await client.post("/api/v1/auth/password-login", json={"email": email, "password": new_password})).status_code == 200
