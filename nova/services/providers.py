"""Process-wide adapters (LLM, ORBIT, FORGE). Overridable for tests and local fixtures."""

from __future__ import annotations

from typing import Any

from nova.agent.providers.factory import build_llm_provider
from nova.config import get_settings
from nova.domain.context import ContextProvider
from nova.domain.design import DesignProvider
from nova.domain.evaluation import EvaluationSink
from nova.domain.llm import LLMProvider
from nova.skills.registry import get_skill_registry

_overrides: dict[str, Any] = {}
_cache: dict[str, Any] = {}


def override(name: str, value: Any) -> None:
    _overrides[name] = value


def reset() -> None:
    _overrides.clear()
    _cache.clear()


def llm() -> LLMProvider:
    if "llm" in _overrides:
        return _overrides["llm"]
    if "llm" not in _cache:
        _cache["llm"] = build_llm_provider(get_settings())
    return _cache["llm"]


def transport() -> Any:
    """Test seam: an httpx transport used for user-supplied LLM providers (None in production)."""
    return _overrides.get("llm_transport")


def http_transport() -> Any:
    """Test seam for outbound webhooks (deploy hooks)."""
    return _overrides.get("http_transport")


async def llm_for_user(user_id: str | None) -> LLMProvider:
    """The user's own model (bring your own key) when configured, else the organization's default."""
    if user_id:
        from nova.services.llm_config import provider_for_user

        own = await provider_for_user(user_id)
        if own is not None:
            return own
    return llm()


def github_client(token: str) -> Any:
    """GitHub client for a user's token; tests install a factory with ``override("github", lambda token: fake)``."""
    if "github" in _overrides:
        return _overrides["github"](token)
    from nova.integrations.github.client import GitHubClient

    return GitHubClient(token)


def context() -> ContextProvider:
    if "context" in _overrides:
        return _overrides["context"]
    if "context" not in _cache:
        from nova.integrations.orbit.adapter import OrbitContextProvider

        _cache["context"] = OrbitContextProvider(get_settings())
    return _cache["context"]


def evaluation() -> EvaluationSink | None:
    if "evaluation" in _overrides:
        return _overrides["evaluation"]
    settings = get_settings()
    if not settings.forge_api_key:
        return None
    if "evaluation" not in _cache:
        from nova.integrations.forge.adapter import ForgeEvaluationSink

        _cache["evaluation"] = ForgeEvaluationSink(settings, get_skill_registry(), settings.llm_model)
    return _cache["evaluation"]


def design() -> DesignProvider:
    if "design" in _overrides:
        return _overrides["design"]
    if "design" not in _cache:
        from nova.integrations.figma.adapter import FigmaDesignProvider

        _cache["design"] = FigmaDesignProvider(get_settings())
    return _cache["design"]
