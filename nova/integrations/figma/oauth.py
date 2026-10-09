"""OAuth 2.1 + PKCE (S256) for Figma's MCP server.

The ``state`` parameter is a Fernet token (authenticated + encrypted with NOVA_SECRETS_KEY) carrying the user id,
the PKCE verifier and an expiry: nothing is stored server side and the verifier never leaves in clear text.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from nova.config import Settings
from nova.domain.design import DesignError
from nova.infra.crypto import decrypt, encrypt

STATE_TTL_SECONDS = 600
FALLBACK_AUTHORIZE = "https://www.figma.com/oauth/mcp"
FALLBACK_TOKEN = "https://api.figma.com/v1/oauth/token"


@dataclass(frozen=True)
class OAuthEndpoints:
    authorize: str
    token: str
    scopes: str = ""


@dataclass(frozen=True)
class OAuthTokens:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scope: str = ""


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def make_state(user_id: str, verifier: str, now: float | None = None) -> str:
    payload = {"u": user_id, "v": verifier, "exp": int((now or time.time()) + STATE_TTL_SECONDS)}
    return encrypt(json.dumps(payload))


def read_state(state: str, now: float | None = None) -> tuple[str, str]:
    """→ (user_id, verifier); raises DesignError('invalid') when forged or expired."""
    plain = decrypt(state)
    try:
        payload = json.loads(plain) if plain else None
        if not isinstance(payload, dict) or int(payload["exp"]) < (now or time.time()):
            raise ValueError
        return str(payload["u"]), str(payload["v"])
    except (ValueError, KeyError, TypeError) as exc:
        raise DesignError("invalid", "The Figma authorization expired or is invalid: start again") from exc


class FigmaOAuth:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self._transport = transport
        self._endpoints: OAuthEndpoints | None = None

    @property
    def available(self) -> bool:
        return bool(self.settings.figma_oauth_client_id)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.settings.figma_timeout_seconds, transport=self._transport)

    async def discover(self) -> OAuthEndpoints:
        """RFC 9728 protected-resource metadata → RFC 8414 authorization-server metadata; Figma defaults on failure."""
        if self._endpoints:
            return self._endpoints
        endpoints = OAuthEndpoints(FALLBACK_AUTHORIZE, FALLBACK_TOKEN)
        mcp = urlsplit(self.settings.figma_mcp_url)
        origin = f"{mcp.scheme}://{mcp.netloc}"
        try:
            async with self._client() as client:
                issuer = origin
                resource = await client.get(f"{origin}/.well-known/oauth-protected-resource")
                if resource.status_code == 200:
                    servers = resource.json().get("authorization_servers") or []
                    if servers:
                        issuer = str(servers[0]).rstrip("/")
                meta = await client.get(f"{issuer}/.well-known/oauth-authorization-server")
                if meta.status_code == 200:
                    data = meta.json()
                    if data.get("authorization_endpoint") and data.get("token_endpoint"):
                        scopes = " ".join(data.get("scopes_supported") or [])
                        endpoints = OAuthEndpoints(str(data["authorization_endpoint"]), str(data["token_endpoint"]), scopes)
        except (httpx.HTTPError, ValueError, AttributeError):
            pass
        self._endpoints = endpoints
        return endpoints

    async def authorize_url(self, user_id: str) -> str:
        if not self.available:
            raise DesignError("unavailable", "Figma OAuth is not configured")
        endpoints = await self.discover()
        verifier, challenge = pkce_pair()
        params = {
            "response_type": "code",
            "client_id": self.settings.figma_oauth_client_id,
            "redirect_uri": self.settings.figma_redirect_uri,
            "state": make_state(user_id, verifier),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if endpoints.scopes:
            params["scope"] = endpoints.scopes
        sep = "&" if "?" in endpoints.authorize else "?"
        return f"{endpoints.authorize}{sep}{urlencode(params)}"

    async def _token_request(self, url: str, data: dict[str, str]) -> OAuthTokens:
        data = {**data, "client_id": self.settings.figma_oauth_client_id}
        if self.settings.figma_oauth_client_secret:
            data["client_secret"] = self.settings.figma_oauth_client_secret
        try:
            async with self._client() as client:
                response = await client.post(url, data=data, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise DesignError("unavailable", "Figma authorization server is unreachable", retryable=True) from exc
        if response.status_code >= 500:
            raise DesignError("unavailable", "Figma authorization server error", retryable=True)
        try:
            body: dict[str, Any] = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400 or not body.get("access_token"):
            raise DesignError("not_connected", "Figma refused the authorization: reconnect Figma in Settings")
        expires_in = body.get("expires_in")
        expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in)) if expires_in else None
        return OAuthTokens(
            access_token=str(body["access_token"]),
            refresh_token=str(body["refresh_token"]) if body.get("refresh_token") else None,
            expires_at=expires_at,
            scope=str(body.get("scope") or ""),
        )

    async def exchange_code(self, code: str, verifier: str) -> OAuthTokens:
        endpoints = await self.discover()
        return await self._token_request(
            endpoints.token,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.figma_redirect_uri,
                "code_verifier": verifier,
            },
        )

    async def refresh(self, refresh_token: str) -> OAuthTokens:
        endpoints = await self.discover()
        tokens = await self._token_request(endpoints.token, {"grant_type": "refresh_token", "refresh_token": refresh_token})
        if tokens.refresh_token is None:  # servers may keep the same refresh token
            tokens = OAuthTokens(tokens.access_token, refresh_token, tokens.expires_at, tokens.scope)
        return tokens
