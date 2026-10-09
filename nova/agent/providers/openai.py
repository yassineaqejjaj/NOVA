"""OpenAI Chat Completions (api.openai.com) and look-alikes that need the newer parameter names."""

from __future__ import annotations

from typing import Any

from nova.agent.providers.openai_compatible import OpenAICompatibleProvider
from nova.domain.llm import LLMMessage

# Reasoning families only accept the default temperature.
_FIXED_TEMPERATURE = ("gpt-5", "o1", "o3", "o4")


class OpenAIProvider(OpenAICompatibleProvider):
    provider_name = "openai"

    def _payload(
        self, messages: list[LLMMessage], temperature: float | None, max_tokens: int | None, **extra: Any
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [m.model_dump() for m in messages],
            "max_completion_tokens": (max_tokens or self.default_max_tokens) + self.reasoning_tokens,
            **extra,
        }
        if not self._model.lower().startswith(_FIXED_TEMPERATURE):
            payload["temperature"] = self.default_temperature if temperature is None else temperature
        return payload
