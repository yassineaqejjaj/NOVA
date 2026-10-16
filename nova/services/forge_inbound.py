"""Who may call the NOVA Agent Protocol (ADR 001 §7, NOV-112): the shared bearer, a service-account token, or either.

``NOVA_FORGE_INBOUND_AUTH``:

* ``token`` (default): the shared bearer ``NOVA_FORGE_INBOUND_TOKEN``, compared in constant time: exactly as before;
* ``oidc``: a client-credentials token of the IdP (audience ``nova-web``, scope ``orion:run.execute``, issued to a service
  account listed in ``NOVA_FORGE_INBOUND_CLIENTS``); the shared bearer is refused;
* ``both``: either of the two (the switch-over window).

The OIDC path never accepts a user's token: the token must be a service account's (no ``act``, no user identity), and it is read
through the ORION claims contract (``nova/domain/orion_claims.py``): a malformed claim refuses it. Every refusal is the same
401 whatever the reason, and nothing about the token reaches a log.
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Any

import jwt

from nova.config import Settings
from nova.domain.orion_claims import ClaimsError, parse_claims
from nova.services.identity import _jwks_client

AUDIENCE = "nova-web"


def _shared_token(token: str, settings: Settings) -> bool:
    return bool(token) and secrets.compare_digest(token.encode(), settings.forge_inbound_token.encode())


def _decode(token: str, settings: Settings) -> dict[str, Any]:
    key = _jwks_client(settings.forge_inbound_jwks_url).get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        key.key,
        algorithms=["RS256"],  # the IdP's algorithm: never "none", never HS256 with a public key as secret
        audience=AUDIENCE,
        issuer=(settings.forge_inbound_issuer or settings.oidc_issuer),
        options={"require": ["exp", "iss", "sub", "aud"]},
    )


def _oidc(token: str, settings: Settings) -> bool:
    if token.count(".") != 2:
        return False
    try:
        payload = _decode(token, settings)
        claims = parse_claims(payload)
    except (jwt.PyJWTError, ClaimsError, OSError, ValueError, KeyError):
        return False
    return (
        claims.is_service  # a service account, never a person
        and claims.actor is None  # and not acting for someone
        and payload.get("azp") in settings.forge_inbound_client_list
        and claims.has_scope(settings.forge_inbound_scope)
    )


async def authorize(token: str, settings: Settings) -> str | None:
    """The method that let the caller in (``token`` / ``oidc``), or ``None``: refused."""
    mode = settings.forge_inbound_auth
    if mode in ("token", "both") and _shared_token(token, settings):
        return "token"
    if mode in ("oidc", "both") and await asyncio.to_thread(_oidc, token, settings):
        return "oidc"
    return None
