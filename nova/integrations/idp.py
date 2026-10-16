"""The identity provider's token endpoint: refresh, token exchange (RFC 8693) and client credentials (NOV-111).

Every function returns what the IdP said or raises ``DelegationError`` with a stable ``code``; none of them ever puts a
token, a secret or a response body in an exception, a log line or an audit trail.
"""

from __future__ import annotations

from typing import Any

import httpx

from nova.config import Settings

TOKEN_TYPE_ACCESS = "urn:ietf:params:oauth:token-type:access_token"
GRANT_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"


class DelegationError(Exception):
    """A delegation that did not happen. ``code`` is stable; ``retryable`` is true when the IdP could not be reached."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


_transport: httpx.AsyncBaseTransport | None = None


def use_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Tests: route the IdP calls to a fake (``None`` restores the network)."""
    global _transport
    _transport = transport


def token_url(settings: Settings) -> str:
    return settings.delegation_token_url or f"{settings.oidc_backchannel}/protocol/openid-connect/token"


def _client_auth(settings: Settings) -> dict[str, str]:
    data = {"client_id": settings.oidc_client_id}
    if settings.oidc_client_secret:
        data["client_secret"] = settings.oidc_client_secret
    return data


def _error(response: httpx.Response, *, subject: bool) -> DelegationError:
    """Map the IdP's refusal to a code, from the OAuth ``error`` / description only (never echoed)."""
    try:
        body = response.json()
        error, description = str(body.get("error", "")), str(body.get("error_description", "")).lower()
    except ValueError:
        error, description = "", ""
    status = response.status_code
    if status >= 500 or status in (408, 425, 429):
        return DelegationError("idp_unavailable", "The identity provider is unavailable", retryable=True)
    if "disabled" in description:
        return DelegationError("user_disabled", "This account is disabled")
    if "audience" in description:
        return DelegationError("audience_refused", "The identity provider does not allow this audience")
    if error == "invalid_scope" or "scope" in description:
        return DelegationError("scope_refused", "The identity provider refused the requested scope")
    if error in ("access_denied", "unauthorized_client") or status == 403:
        return DelegationError("exchange_forbidden", "The identity provider refused the exchange")
    if (
        error in ("invalid_grant", "invalid_token")
        or status == 401
        or subject
        or ("token" in description and any(w in description for w in ("invalid", "expired", "inactive")))
    ):
        # expired, revoked, or the user is disabled: the user's own token is no longer good
        return DelegationError("subject_expired", "Your sign-in is no longer valid: sign in again")
    return DelegationError("exchange_refused", "The identity provider refused the request")


async def _post(settings: Settings, data: dict[str, str], *, subject: bool) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=settings.delegation_timeout_seconds, transport=_transport) as client:
            response = await client.post(token_url(settings), data=data)
    except httpx.HTTPError as exc:
        raise DelegationError("idp_unavailable", "The identity provider is unreachable", retryable=True) from exc
    if response.status_code != 200:
        raise _error(response, subject=subject)
    try:
        body = response.json()
    except ValueError as exc:
        raise DelegationError("idp_invalid", "The identity provider answered something unreadable") from exc
    if not isinstance(body, dict) or not isinstance(body.get("access_token"), str):
        raise DelegationError("idp_invalid", "The identity provider answered without a token")
    return body


async def refresh(settings: Settings, refresh_token: str) -> dict[str, Any]:
    return await _post(
        settings, {"grant_type": "refresh_token", "refresh_token": refresh_token, **_client_auth(settings)}, subject=True
    )


async def exchange(
    settings: Settings, subject_token: str, *, audience: str, scope: str, orion_project_id: str | None
) -> dict[str, Any]:
    data = {
        "grant_type": GRANT_EXCHANGE,
        "subject_token": subject_token,
        "subject_token_type": TOKEN_TYPE_ACCESS,
        "requested_token_type": TOKEN_TYPE_ACCESS,
        "audience": audience,
        # Keycloak only exchanges towards an audience held as a client scope, and the scope names it (observed, NOV-103)
        "scope": f"orion-audience-{audience} {scope}",
        **_client_auth(settings),
    }
    if orion_project_id:
        data["orion_project_id"] = orion_project_id  # the target project (ADR §6); the IdP maps it into the token
    return await _post(settings, data, subject=False)


async def client_credentials(settings: Settings, *, audience: str, scope: str) -> dict[str, Any]:
    """The service account's own token (no user): the audience is asked as a scope (``orion-audience-<service>``)."""
    if not settings.delegation_service_client_secret:
        raise DelegationError("service_not_configured", "No service account is configured for delegation")
    data = {
        "grant_type": "client_credentials",
        "client_id": settings.delegation_service_client_id,
        "client_secret": settings.delegation_service_client_secret,
        "scope": f"orion-audience-{audience} {scope}",
    }
    return await _post(settings, data, subject=False)
