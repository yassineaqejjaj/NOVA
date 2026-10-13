"""Registering a NOVA agent version in FORGE without ever reusing one registered for another connection.

FORGE versions are immutable and their label is unique per agent: creating the same label again answers ``409``.
Reusing the version found under that label is only right when it was registered with the same connection (endpoint and
credential) — otherwise FORGE would keep calling a stale URL, or call NOVA without credential. A mismatch registers a
new version under a label made unique by the fingerprint of the body.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from nova.infra.db import session_scope
from nova.infra.models import IntegrationReference
from nova.integrations.forge import mapper
from nova.integrations.forge.client import ForgeClient, ForgeError

LABEL_MAX = 40  # FORGE's limit for a version label


def _credential_of(version: dict[str, Any]) -> str | None:
    credential = version.get("credential")
    found = (credential.get("id") if isinstance(credential, dict) else None) or version.get("credential_id")
    return str(found) if found else None


def matches(version: dict[str, Any], body: dict[str, Any]) -> bool:
    """The FORGE version was registered with the endpoint and credential of ``body``."""
    same_endpoint = (version.get("endpoint") or "").rstrip("/") == (body.get("endpoint") or "").rstrip("/")
    wanted = body.get("credential_id")
    return same_endpoint and _credential_of(version) == (str(wanted) if wanted else None)


def unique_label(body: dict[str, Any]) -> str:
    suffix = "." + mapper.version_key(body)[:6]
    return body["version"][: LABEL_MAX - len(suffix)] + suffix


async def _existing(client: ForgeClient, agent_id: str, label: str) -> dict[str, Any] | None:
    return next((v for v in await client.list_agent_versions(agent_id) if v.get("version") == label), None)


async def register_agent_version(client: ForgeClient, agent_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Create the version, or find the one already registered for this connection; else register a new one."""
    try:
        return await client.create_agent_version(agent_id, body)
    except ForgeError as exc:
        if exc.status != 409:
            raise
        found = await _existing(client, agent_id, body["version"])
        if found is None:
            raise
        if matches(found, body):
            return found
    variant = {**body, "version": unique_label(body)}
    try:
        return await client.create_agent_version(agent_id, variant)
    except ForgeError as exc:
        if exc.status != 409:
            raise
        found = await _existing(client, agent_id, variant["version"])
        if found is None or not matches(found, variant):
            raise
        return found


def _reference(nova_type: str, key: str):
    return select(IntegrationReference).where(
        IntegrationReference.system == "forge",
        IntegrationReference.kind == "agent_version",
        IntegrationReference.nova_type == nova_type,
        IntegrationReference.nova_id == key,
    )


async def cached_version_id(nova_type: str, key: str, link: str) -> str | None:
    """The FORGE version remembered for ``key``, only when it was registered for this connection (``link``)."""
    async with session_scope() as session:
        row = await session.scalar(_reference(nova_type, key))
        return row.external_id if row and row.data.get("connection") == link else None


async def remember_version(nova_type: str, key: str, link: str, version_id: str, data: dict[str, Any]) -> None:
    """Remember (or replace) the FORGE version of ``key``: a new connection supersedes the version cached before."""
    data = {**data, "connection": link}
    async with session_scope() as session:
        row = await session.scalar(_reference(nova_type, key))
        if row is None:
            session.add(
                IntegrationReference(
                    system="forge", kind="agent_version", nova_type=nova_type, nova_id=key, external_id=version_id, data=data
                )
            )
        else:
            row.external_id, row.data = version_id, data
