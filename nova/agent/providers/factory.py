"""Build the configured LLM provider (``llm.provider`` / ``base_url`` / ``model`` are configuration)."""

from __future__ import annotations

from nova.agent.providers.anthropic import AnthropicProvider
from nova.agent.providers.openai_compatible import OpenAICompatibleProvider
from nova.agent.providers.vllm import VLLMProvider
from nova.config import Settings
from nova.domain.llm import LLMProvider

PROVIDERS: dict[str, type[OpenAICompatibleProvider]] = {
    "vllm": VLLMProvider,
    "openai_compatible": OpenAICompatibleProvider,
    "anthropic": AnthropicProvider,
}


def build_llm_provider(settings: Settings) -> LLMProvider:
    cls = PROVIDERS[settings.llm_provider]
    base_url = settings.llm_base_url
    if settings.llm_provider == "anthropic" and "anthropic.com" not in base_url:
        base_url = ""  # the self-hosted default does not apply: use the Anthropic API
    return cls(
        base_url,
        settings.llm_model,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout_seconds,
        default_temperature=settings.llm_temperature,
        default_max_tokens=settings.llm_max_tokens,
        reasoning_tokens=settings.llm_reasoning_tokens,
    )
