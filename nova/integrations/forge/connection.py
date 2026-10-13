"""How FORGE reaches NOVA back: one endpoint and one credential for capture, training and SDLC ingestion.

FORGE's ``nova`` adapter calls ``POST {endpoint}/v1/agents/{id}/runs`` with the secret of ``credential_id`` as Bearer
token. The endpoint is NOVA's **API** as FORGE's runner sees it (never the web frontend, which does not serve that route).
"""

from __future__ import annotations

import hashlib
from urllib.parse import urlparse

from nova.config import Settings

DEV_WEB_PORT, DEV_API_PORT = ":3200", ":8200"


class ForgeConfigurationError(Exception):
    """The FORGE ↔ NOVA connection cannot work as configured (raised before anything is registered in FORGE)."""


def forge_callback_endpoint(settings: Settings) -> str:
    """``NOVA_FORGE_NOVA_ENDPOINT``, else (local development) the web URL moved to the API port."""
    return (settings.forge_nova_endpoint or settings.public_url.replace(DEV_WEB_PORT, DEV_API_PORT)).rstrip("/")


def forge_credential(settings: Settings) -> str | None:
    """Id of FORGE's ``nova`` credential (its secret is ``NOVA_FORGE_INBOUND_TOKEN``), ``None`` when not configured."""
    return settings.forge_credential_id or None


def connection_key(endpoint: str, credential_id: str | None) -> str:
    """Fingerprint of the connection an agent version was registered with (a change means a new version)."""
    return hashlib.sha256(f"{endpoint}|{credential_id or ''}".encode()).hexdigest()[:12]


def endpoint_problem(settings: Settings, endpoint: str | None = None) -> str | None:
    """Why the callback endpoint cannot be NOVA's API, or ``None``; an explicit ``endpoint`` replaces the configured one."""
    url = urlparse(endpoint or forge_callback_endpoint(settings))
    if url.scheme not in ("http", "https") or not url.hostname:
        return "NOVA_FORGE_NOVA_ENDPOINT is not an http(s) URL"
    if endpoint is None and not settings.forge_nova_endpoint and DEV_WEB_PORT not in settings.public_url:
        return "NOVA_FORGE_NOVA_ENDPOINT is not set and NOVA_PUBLIC_URL is the web frontend, not the API"
    return None


def connection_problems(settings: Settings, *, endpoint: str | None = None, credential_id: str | None = None) -> list[str]:
    """What stops FORGE from calling NOVA back (empty when it can); explicit values replace the configured ones."""
    problems = [endpoint_problem(settings, endpoint)]
    if not (credential_id or forge_credential(settings)):
        problems.append("NOVA_FORGE_CREDENTIAL_ID is not set (FORGE would call NOVA without credential)")
    return [p for p in problems if p]


def require_connection(settings: Settings, *, endpoint: str | None = None, credential_id: str | None = None) -> None:
    if problems := connection_problems(settings, endpoint=endpoint, credential_id=credential_id):
        raise ForgeConfigurationError("FORGE cannot call NOVA back: " + "; ".join(problems))
