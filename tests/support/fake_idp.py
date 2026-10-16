"""A fake identity provider for delegation tests (NOV-111): refresh, token exchange (RFC 8693), client credentials.

It behaves like the Keycloak 26.8 realm ``orion`` observed in NOV-103: an exchange needs the audience as a client scope
(``orion-audience-<service>``), refuses an audience or a scope it does not know, refuses a disabled user and an expired
subject token. Tokens are RS256, signed by a throw-away key; no secret is real.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any
from urllib.parse import parse_qs

import httpx

from tests.contract.support import load_script

gen = load_script("generate_claims_fixtures")
ISSUER = gen.ISSUER
WORKSPACE = gen.WS_A
OTHER_WORKSPACE = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
USER_SUB = gen.USER


class FakeIdP:
    def __init__(self) -> None:
        self.key = gen.new_key()
        self.calls: list[dict[str, str]] = []
        self.disabled: set[str] = set()
        self.lifespan = 300  # of the delegated token
        self.audiences = {"orbit", "forge"}
        self.scopes = {"orion:context.read", "orion:run.execute"}
        self.actor: str | None = None  # add an ``act`` claim
        self.wrong_sub = False
        self.refresh_valid = True
        self.unavailable = False
        self.now = time.time

    # -- tokens -----------------------------------------------------------------------------------------------------

    def token(self, *, sub: str, aud: str, lifespan: int, scope: str = "", **extra: Any) -> str:
        now = int(self.now())
        payload = {
            "iss": ISSUER,
            "sub": sub,
            "aud": aud,
            "iat": now,
            "exp": now + lifespan,
            "email": "alice@example.test",
            "email_verified": True,
            "orion_workspace_id": WORKSPACE,
            "orion_clearance": 2,
            "amr": ["pwd"],
            "scope": scope,
            **extra,
        }
        return gen.sign_jwt(self.key, payload)

    def sign_in(self, *, sub: str = USER_SUB, lifespan: int = 300) -> dict[str, Any]:
        """What the OIDC callback receives from the IdP (the user's own tokens)."""
        return {
            "access_token": self.token(sub=sub, aud="nova-web", lifespan=lifespan),
            "refresh_token": f"refresh-{uuid.uuid4().hex}",
            "expires_in": lifespan,
            "refresh_expires_in": 1800,
        }

    # -- the endpoint -----------------------------------------------------------------------------------------------

    def handler(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.calls.append(form)
        if self.unavailable:
            return httpx.Response(503, text="down")
        grant = form["grant_type"]
        if grant == "refresh_token":
            if not self.refresh_valid or form["refresh_token"].startswith("revoked"):
                return _err(400, "invalid_grant", "Token is not active")
            body = self.sign_in()
            return httpx.Response(200, json=body)
        if grant == "client_credentials":
            wanted = form["scope"].split()
            audience = next((s.removeprefix("orion-audience-") for s in wanted if s.startswith("orion-audience-")), "")
            if audience not in self.audiences:
                return _err(400, "invalid_scope", "Invalid scopes")
            return httpx.Response(
                200,
                json={
                    "access_token": self.token(
                        sub=gen.SERVICE_SUB,
                        aud=audience,
                        lifespan=300,
                        scope=" ".join(s for s in wanted if s.startswith("orion:")),
                        preferred_username="service-account-nova-service",
                        **({"act": {"sub": "x"}} if self.actor else {}),
                    )
                },
            )
        assert grant == "urn:ietf:params:oauth:grant-type:token-exchange"
        subject = json.loads(__import__("base64").urlsafe_b64decode(form["subject_token"].split(".")[1] + "=="))
        if subject["exp"] <= self.now():
            return _err(400, "invalid_token", "Invalid token")
        if subject["sub"] in self.disabled:
            return _err(400, "invalid_request", "User is disabled")
        audience, scopes = form["audience"], form["scope"].split()
        if audience not in self.audiences or f"orion-audience-{audience}" not in scopes:
            return _err(400, "invalid_request", f"Requested audience not available: {audience}")
        asked = {s for s in scopes if s.startswith("orion:")}
        if not asked <= self.scopes:
            return _err(400, "invalid_scope", "Invalid scopes")
        extra: dict[str, Any] = {}
        if form.get("orion_project_id"):
            extra["orion_project_id"] = form["orion_project_id"]
        if self.actor:
            extra["act"] = {"sub": self.actor, "client_id": "nova-web"}
        sub = "5b1d0000-0000-4000-8000-0000000000ff" if self.wrong_sub else subject["sub"]
        token = self.token(sub=sub, aud=audience, lifespan=self.lifespan, scope=" ".join(sorted(asked)), **extra)
        return httpx.Response(200, json={"access_token": token, "issued_token_type": form["requested_token_type"]})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def _err(status: int, error: str, description: str) -> httpx.Response:
    return httpx.Response(status, json={"error": error, "error_description": description})
