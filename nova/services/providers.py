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
