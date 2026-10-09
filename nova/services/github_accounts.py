"""GitHub link of a user: a personal access token, encrypted at rest."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from nova.infra.crypto import decrypt, encrypt
from nova.infra.db import session_scope
from nova.infra.models import GithubAccount
from nova.integrations.github.client import GitHubClient, GitHubError


def make_client(token: str) -> GitHubClient:
    from nova.services import providers

    return providers.github_client(token)


async def status(session: AsyncSession, user_id: str) -> dict[str, Any]:
    row = await session.get(GithubAccount, uuid.UUID(user_id))
    if row is None:
        return {"linked": False, "login": None, "scopes": "", "can_write": False}
    scopes = {s.strip() for s in row.scopes.split(",") if s.strip()}
    # Classic tokens expose scopes; fine-grained tokens expose none (permissions are checked per repository).
    return {
        "linked": True,
        "login": row.login,
        "scopes": row.scopes,
        "can_write": (not scopes) or "repo" in scopes or "public_repo" in scopes,
    }


async def link(session: AsyncSession, user_id: str, token: str) -> dict[str, Any]:
    token = token.strip()
    client = make_client(token)
    try:
        viewer = await client.viewer()
    finally:
        await client.aclose()
    row = await session.get(GithubAccount, uuid.UUID(user_id))
    if row is None:
        row = GithubAccount(user_id=uuid.UUID(user_id), token_ciphertext="")
        session.add(row)
    row.token_ciphertext = encrypt(token)
    row.login = viewer["login"]
    row.scopes = viewer["scopes"]
    await session.flush()
    return await status(session, user_id)


async def unlink(session: AsyncSession, user_id: str) -> bool:
    row = await session.get(GithubAccount, uuid.UUID(user_id))
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def token_for(user_id: str) -> str | None:
    async with session_scope() as session:
        row = await session.get(GithubAccount, uuid.UUID(user_id))
    return decrypt(row.token_ciphertext) if row else None


async def client_for(user_id: str) -> GitHubClient:
    token = await token_for(user_id)
    if not token:
        raise GitHubError("unauthorized", "Connect GitHub in Settings first.")
    return make_client(token)
