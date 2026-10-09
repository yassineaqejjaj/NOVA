"""LLM providers a user can bring their own API key for (Settings → AI model)."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

from nova.agent.providers.anthropic import ANTHROPIC_BASE_URL, AnthropicProvider
from nova.agent.providers.openai import OpenAIProvider
from nova.agent.providers.openai_compatible import OpenAICompatibleProvider
from nova.config import Settings
from nova.domain.llm import LLMError, LLMProvider


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    label: str
    base_url: str  # "" = the user supplies it
    default_model: str
    models: tuple[str, ...]
    key_hint: str  # prefix shown as placeholder
    external: bool = True  # prompts leave the organization's perimeter


CATALOG: dict[str, ProviderInfo] = {
    "anthropic": ProviderInfo(
        "anthropic",
        "Anthropic (Claude)",
        ANTHROPIC_BASE_URL,
        "claude-sonnet-5-5",
        ("claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5", "claude-sonnet-4-5", "claude-haiku-4-5"),
        "sk-ant-…",
    ),
    "openai": ProviderInfo(
        "openai", "OpenAI", "https://api.openai.com/v1", "gpt-5", ("gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4o"), "sk-…"
    ),
    "google": ProviderInfo(
        "google",
        "Google Gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "gemini-2.5-pro",
        ("gemini-2.5-pro", "gemini-2.5-flash"),
        "AIza…",
    ),
    "mistral": ProviderInfo(
        "mistral",
        "Mistral AI",
        "https://api.mistral.ai/v1",
        "mistral-large-latest",
        ("mistral-large-latest", "codestral-latest"),
        "",
    ),
    "openrouter": ProviderInfo(
        "openrouter",
        "OpenRouter",
        "https://openrouter.ai/api/v1",
        "anthropic/claude-sonnet-4.5",
        ("anthropic/claude-sonnet-4.5", "openai/gpt-5", "google/gemini-2.5-pro"),
        "sk-or-…",
    ),
    "custom": ProviderInfo("custom", "OpenAI-compatible endpoint", "", "", (), "", external=True),
}


def validate_base_url(url: str, *, allow_private: bool) -> str:
    """HTTPS endpoint on the public internet (the server calls it: no access to internal networks)."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise LLMError("The base URL must be a valid http(s) URL")
    if allow_private:
        return url.strip().rstrip("/")
    if parts.scheme != "https":
        raise LLMError("The base URL must use https")
    host = parts.hostname
    if host == "localhost" or host.endswith((".internal", ".local", ".localhost")):
        raise LLMError("Private and internal addresses are not allowed")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)}
    except socket.gaierror as exc:
        raise LLMError("The base URL host could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise LLMError("Private and internal addresses are not allowed")
    return url.strip().rstrip("/")


def build_user_provider(
    provider: str, model: str, api_key: str, base_url: str, settings: Settings, *, transport=None
) -> LLMProvider:
    info = CATALOG.get(provider)
    if info is None:
        raise LLMError(f"Unknown provider '{provider}'")
    model = (model or info.default_model).strip()
    if not model:
        raise LLMError("Choose a model")
    common = dict(
        api_key=api_key,
        timeout=max(settings.llm_timeout_seconds, 180.0),  # code generation produces long outputs
        default_temperature=settings.llm_temperature,
        default_max_tokens=settings.llm_max_tokens,
        transport=transport,
    )
    if provider == "anthropic":
        return AnthropicProvider(info.base_url, model, **common)
    if provider == "openai":
        return OpenAIProvider(info.base_url, model, **common)
    if provider == "custom":
        if not base_url:
            raise LLMError("The endpoint URL is required")
        url = validate_base_url(base_url, allow_private=settings.env != "production")
        return OpenAICompatibleProvider(url, model, **common)
    return OpenAICompatibleProvider(info.base_url, model, **common)
