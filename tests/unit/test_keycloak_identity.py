"""Keycloak identity backend: Admin API calls and password grant, against a fake Keycloak."""

from __future__ import annotations

import json

import httpx
import pytest

from nova.config import Settings
from nova.services import identity
from nova.services.identity import IdentityError, KeycloakIdentity

SETTINGS = Settings(auth_mode="oidc", oidc_issuer="https://kc.test/realms/nova", oidc_client_secret="s" * 32)


class FakeKeycloak:
    def __init__(self) -> None:
        self.users: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        if path.endswith("/protocol/openid-connect/token"):
            form = dict(httpx.QueryParams(request.content.decode()))
            assert form["client_secret"] == "s" * 32
            if form["grant_type"] == "client_credentials":
                return httpx.Response(200, json={"access_token": "admin", "expires_in": 300})
            user = next((u for u in self.users.values() if u["email"] == form["username"]), None)
            if user is None or user["password"] != form["password"]:
                return httpx.Response(401, json={"error": "invalid_grant", "error_description": "Invalid user credentials"})
            if not user["enabled"]:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Account disabled"})
            return httpx.Response(200, json={"id_token": f"id:{user['id']}"})
        assert request.headers["authorization"] == "Bearer admin"
        assert path.startswith("/admin/realms/nova/users")
        if request.method == "GET":
            email = request.url.params["email"]
            return httpx.Response(200, json=[u for u in self.users.values() if u["email"] == email])
        if request.method == "POST":
            body = json.loads(request.content)
            uid = f"u{len(self.users) + 1}"
            self.users[uid] = {**body, "id": uid, "password": body["credentials"][0]["value"]}
            return httpx.Response(201)
        uid = path.split("/")[5]
        body = json.loads(request.content)
        if path.endswith("/reset-password"):
            self.users[uid]["password"] = body["value"]
        else:
            self.users[uid].update(body)
        return httpx.Response(204)


@pytest.fixture
def keycloak(monkeypatch):
    fake = FakeKeycloak()
    monkeypatch.setattr(
        identity,
        "validate_oidc_token",
        lambda token, settings, audience: {
            "sub": token.split(":")[1],
            "email": "camille@devoteam.com",
            "name": "Camille Martin",
            "email_verified": True,
            "realm_access": {"roles": ["nova-user", "offline_access"]},
        },
    )
    return fake, KeycloakIdentity(SETTINGS, httpx.MockTransport(fake.handler))


async def test_account_is_created_disabled_then_activated_and_signs_in(keycloak):
    fake, backend = keycloak
    user = await backend.create("camille@devoteam.com", "Camille Martin", "Orbit-and-forge-2026")
    stored = fake.users[user.subject]
    assert stored["enabled"] is False and stored["emailVerified"] is False
    assert (stored["firstName"], stored["lastName"]) == ("Camille", "Martin")

    with pytest.raises(IdentityError) as pending:
        await backend.authenticate("camille@devoteam.com", "Orbit-and-forge-2026")
    assert pending.value.code == "email_not_verified"

    await backend.activate(user)
    assert stored["enabled"] is True and stored["emailVerified"] is True
    signed_in = await backend.authenticate("camille@devoteam.com", "Orbit-and-forge-2026")
    assert signed_in.subject == user.subject and signed_in.roles == ["nova-user"]

    with pytest.raises(IdentityError) as wrong:
        await backend.authenticate("camille@devoteam.com", "nope")
    assert wrong.value.code == "invalid_credentials"

    await backend.set_password(user, "A-brand-new-password-7")
    assert (await backend.authenticate("camille@devoteam.com", "A-brand-new-password-7")).subject == user.subject
    assert sum(1 for m, p in fake.calls if p.endswith("/token")) >= 4
