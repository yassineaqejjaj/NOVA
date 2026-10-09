"""Bring-your-own-key: the user's preferred LLM and its API key (encrypted at rest, never returned)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from nova.agent.providers.catalog import CATALOG, build_user_provider
from nova.config import get_settings
from nova.domain.llm import LLMError, LLMMessage, LLMProvider
from nova.infra.crypto import decrypt, encrypt
from nova.infra.db import session_scope, utcnow
from nova.infra.models import UserLLMConfig

_cache: dict[tuple[str, str, str], LLMProvider] = {}
MAX_CACHE = 64


def public_view(config: UserLLMConfig | None) -> dict[str, Any]:
    """What the API returns: never the key, only whether one is stored and its last characters."""
    return {
        "providers": [
            {
                "id": p.id,
                "label": p.label,
                "default_model": p.default_model,
                "models": list(p.models),
                "key_hint": p.key_hint,
                "needs_base_url": p.id == "custom",
            }
            for p in CATALOG.values()
        ],
        "configured": config is not None,
        "provider": config.provider if config else None,
        "model": config.model if config else None,
        "base_url": config.base_url if config else "",
        "key_hint": config.key_hint if config else "",
        "verified_at": config.verified_at.isoformat() if config and config.verified_at else None,
        "default_model": get_settings().llm_model,
    }


async def get_config(session: AsyncSession, user_id: str) -> UserLLMConfig | None:
    return await session.get(UserLLMConfig, uuid.UUID(user_id))


def _build(config_provider: str, model: str, key: str, base_url: str) -> LLMProvider:
    from nova.services import providers

    return build_user_provider(config_provider, model, key, base_url, get_settings(), transport=providers.transport())


async def check_connection(provider: LLMProvider) -> None:
    """One tiny request: proves the key, the model name and the endpoint work before anything is saved."""
    result = await provider.generate(
        [LLMMessage(role="user", content="Reply with the single word OK.")], max_tokens=32, temperature=0
    )
    if not result.text.strip():
        raise LLMError("The model answered with an empty message")


async def save_config(
    session: AsyncSession, user_id: str, *, provider: str, model: str, api_key: str | None, base_url: str = ""
) -> UserLLMConfig:
    existing = await get_config(session, user_id)
    key = (api_key or "").strip()
    if not key:
        if existing is None or existing.provider != provider:
            raise LLMError("Enter your API key")
        key = decrypt(existing.key_ciphertext) or ""
        if not key:
            raise LLMError("The stored key can no longer be read: enter it again")
    info = CATALOG.get(provider)
    if info is None:
        raise LLMError(f"Unknown provider '{provider}'")
    model = (model or info.default_model).strip()
    llm = _build(provider, model, key, base_url if provider == "custom" else "")
    await check_connection(llm)
    row = existing or UserLLMConfig(user_id=uuid.UUID(user_id))
    row.provider, row.model = provider, model
    row.base_url = base_url.strip() if provider == "custom" else ""
    row.key_ciphertext = encrypt(key)
    row.key_hint = key[-4:] if len(key) >= 12 else ""
    row.verified_at = utcnow()
    if existing is None:
        session.add(row)
    await session.flush()
    _cache.clear()
    return row


async def delete_config(session: AsyncSession, user_id: str) -> bool:
    row = await get_config(session, user_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    _cache.clear()
    return True


async def provider_for_user(user_id: str) -> LLMProvider | None:
    """The user's own model, or ``None`` when they did not configure one."""
    async with session_scope() as session:
        row = await get_config(session, user_id)
    if row is None:
        return None
    cache_key = (user_id, row.key_ciphertext[-24:], f"{row.provider}:{row.model}:{row.base_url}")
    if cache_key not in _cache:
        key = decrypt(row.key_ciphertext)
        if not key:
            raise LLMError("Your stored API key can no longer be read: enter it again in Settings → AI model")
        if len(_cache) >= MAX_CACHE:
            _cache.clear()
        _cache[cache_key] = _build(row.provider, row.model, key, row.base_url)
    return _cache[cache_key]
