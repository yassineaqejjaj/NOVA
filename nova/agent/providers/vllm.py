"""vLLM provider (first-class inference engine of NOVA).

vLLM exposes the OpenAI-compatible API; structured outputs use its guided decoding through
``response_format: json_schema`` (supported by the xgrammar / outlines backends), which guarantees
schema-conforming JSON from open-weight models.
"""

from __future__ import annotations

from typing import Any

from nova.agent.providers.openai_compatible import OpenAICompatibleProvider


class VLLMProvider(OpenAICompatibleProvider):
    provider_name = "vllm"

    def _structured_params(self, name: str, schema: dict[str, Any]) -> dict[str, Any]:
        return {"response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}}}
