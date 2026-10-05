"""Anthropic Claude provider (Messages API).

Same contract as the OpenAI-compatible providers: plain generation, streaming and schema-constrained
structured output. Structured output uses a forced tool call (``tool_choice``) whose ``input_schema`` is the
JSON schema NOVA already validates against, so the validation/repair loop is shared.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from nova.agent.providers.openai_compatible import RETRYABLE_STATUS, OpenAICompatibleProvider, tracer
from nova.domain.llm import LLMError, LLMMessage, LLMResult
from nova.domain.outputs import TokenUsage

ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5-5"
STRUCTURED_TOOL = "submit_result"
RETRYABLE_ANTHROPIC = RETRYABLE_STATUS | {529}  # 529: overloaded


class AnthropicProvider(OpenAICompatibleProvider):
    provider_name = "anthropic"

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str = "",
        timeout: float = 120.0,
        default_temperature: float = 0.2,
        default_max_tokens: int = 4096,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise LLMError("No Anthropic API key configured (NOVA_LLM_API_KEY)")
        super().__init__(
            base_url or ANTHROPIC_BASE_URL,
            model or DEFAULT_MODEL,
            timeout=timeout,
            default_temperature=default_temperature,
            default_max_tokens=default_max_tokens,
            transport=transport,
        )
        self._client.headers.update(
            {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}
        )

    # --- Request shaping ----------------------------------------------------------------------------

    def _structured_params(self, name: str, schema: dict[str, Any]) -> dict[str, Any]:
        return {
            "tools": [{"name": STRUCTURED_TOOL, "description": f"Return the {name} result.", "input_schema": schema}],
            "tool_choice": {"type": "tool", "name": STRUCTURED_TOOL},
        }

    def _payload(
        self, messages: list[LLMMessage], temperature: float | None, max_tokens: int | None, **extra: Any
    ) -> dict[str, Any]:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        turns: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                continue
            if turns and turns[-1]["role"] == m.role:  # the API requires alternating roles
                turns[-1]["content"] += "\n\n" + m.content
            else:
                turns.append({"role": m.role, "content": m.content})
        if not turns or turns[0]["role"] != "user":
            turns.insert(0, {"role": "user", "content": "(continue)"})
        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens or self.default_max_tokens,
            "temperature": self.default_temperature if temperature is None else temperature,
            "messages": turns,
            **extra,
        }
        if system:
            payload["system"] = system
        return payload

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post("/messages", json=payload)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:
            raise LLMError(f"Anthropic API unreachable ({exc.__class__.__name__})", retryable=True) from exc
        if response.status_code >= 400:
            raise LLMError(
                f"Anthropic API error {response.status_code}: {response.text[:200]}",
                retryable=response.status_code in RETRYABLE_ANTHROPIC,
            )
        return response.json()

    # --- LLMProvider ----------------------------------------------------------------------------------

    async def generate(
        self, messages: list[LLMMessage], *, temperature: float | None = None, max_tokens: int | None = None, **extra: Any
    ) -> LLMResult:
        with tracer.start_as_current_span(f"chat {self._model}") as span:
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.system", "anthropic")
            span.set_attribute("gen_ai.request.model", self._model)
            started = time.perf_counter()
            data = await self._post(self._payload(messages, temperature, max_tokens, **extra))
            latency = (time.perf_counter() - started) * 1000
            try:
                blocks = data["content"]
                tool = next((b for b in blocks if b.get("type") == "tool_use"), None)
                # A forced tool call returns the structured result as the tool input; plain calls return text.
                text = (
                    json.dumps(tool["input"]) if tool else "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
                )
            except (KeyError, TypeError) as exc:
                raise LLMError("Malformed response from the Anthropic API") from exc
            usage_raw = data.get("usage") or {}
            usage = TokenUsage(
                input_tokens=int(usage_raw.get("input_tokens") or 0),
                output_tokens=int(usage_raw.get("output_tokens") or 0),
                model_calls=1,
            )
            span.set_attribute("gen_ai.response.model", str(data.get("model") or self._model))
            span.set_attribute("gen_ai.usage.input_tokens", usage.input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", usage.output_tokens)
            if data.get("stop_reason"):
                span.set_attribute("gen_ai.response.finish_reasons", [str(data["stop_reason"])])
            return LLMResult(
                text=text,
                model=str(data.get("model") or self._model),
                usage=usage,
                finish_reason=data.get("stop_reason"),
                latency_ms=latency,
            )

    async def stream(
        self, messages: list[LLMMessage], *, temperature: float | None = None, max_tokens: int | None = None
    ) -> AsyncIterator[str]:
        payload = self._payload(messages, temperature, max_tokens, stream=True)
        try:
            async with self._client.stream("POST", "/messages", json=payload) as response:
                if response.status_code >= 400:
                    raise LLMError(
                        f"Anthropic API error {response.status_code}", retryable=response.status_code in RETRYABLE_ANTHROPIC
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    event = json.loads(line[5:].strip() or "{}")
                    if event.get("type") == "content_block_delta" and event.get("delta", {}).get("type") == "text_delta":
                        yield event["delta"].get("text", "")
                    elif event.get("type") == "message_stop":
                        break
        except httpx.HTTPError as exc:
            raise LLMError("Anthropic API unreachable", retryable=True) from exc
