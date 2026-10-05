"""OpenAI-compatible chat completions client for self-hosted inference servers.

Works with vLLM, llama.cpp server, Ollama, LocalAI, TGI… (all open source). No proprietary SaaS:
the base URL is always configured by the operator.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator
from typing import Any, TypeVar

import httpx
from jsonschema import Draft202012Validator
from opentelemetry import trace
from pydantic import BaseModel, ValidationError

from nova.domain.llm import LLMError, LLMMessage, LLMResult, StructuredResult
from nova.domain.outputs import TokenUsage

T = TypeVar("T", bound=BaseModel)
tracer = trace.get_tracer("nova.llm")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def extract_json(text: str) -> Any:
    """Parse the first JSON object of a completion (tolerates fences and leading prose)."""
    cleaned = _FENCE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


TRUNCATED = {"length", "max_tokens"}
MAX_STRUCTURED_TOKENS = 32_000


class OpenAICompatibleProvider:
    provider_name = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str = "",
        timeout: float = 120.0,
        default_temperature: float = 0.2,
        default_max_tokens: int = 4096,
        reasoning_tokens: int = 0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.reasoning_tokens = reasoning_tokens
        if not model:
            raise LLMError("No model configured (NOVA_LLM_MODEL)")
        self.base_url = base_url.rstrip("/")
        self._model = model
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout, headers=headers, transport=transport)

    @property
    def model_name(self) -> str:
        return self._model

    async def aclose(self) -> None:
        await self._client.aclose()

    # --- Request shaping (overridden by VLLMProvider) -------------------------------------------

    def _structured_params(self, name: str, schema: dict[str, Any]) -> dict[str, Any]:
        return {"response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema}}}

    def _payload(
        self, messages: list[LLMMessage], temperature: float | None, max_tokens: int | None, **extra: Any
    ) -> dict[str, Any]:
        return {
            "model": self._model,
            "messages": [m.model_dump() for m in messages],
            "temperature": self.default_temperature if temperature is None else temperature,
            "max_tokens": (max_tokens or self.default_max_tokens) + self.reasoning_tokens,
            **extra,
        }

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post("/chat/completions", json=payload)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:
            raise LLMError(f"Inference server unreachable ({exc.__class__.__name__})", retryable=True) from exc
        if response.status_code >= 400:
            raise LLMError(
                f"Inference server error {response.status_code}: {response.text[:200]}",
                retryable=response.status_code in RETRYABLE_STATUS,
            )
        return response.json()

    # --- LLMProvider ---------------------------------------------------------------------------

    async def generate(
        self, messages: list[LLMMessage], *, temperature: float | None = None, max_tokens: int | None = None, **extra: Any
    ) -> LLMResult:
        with tracer.start_as_current_span(f"chat {self._model}") as span:
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.system", self.provider_name)
            span.set_attribute("gen_ai.request.model", self._model)
            started = time.perf_counter()
            data = await self._post(self._payload(messages, temperature, max_tokens, **extra))
            latency = (time.perf_counter() - started) * 1000
            try:
                choice = data["choices"][0]
                text = choice["message"].get("content") or ""
            except (KeyError, IndexError, TypeError) as exc:
                raise LLMError("Malformed response from inference server") from exc
            usage_raw = data.get("usage") or {}
            usage = TokenUsage(
                input_tokens=int(usage_raw.get("prompt_tokens") or 0),
                output_tokens=int(usage_raw.get("completion_tokens") or 0),
                model_calls=1,
            )
            span.set_attribute("gen_ai.response.model", str(data.get("model") or self._model))
            span.set_attribute("gen_ai.usage.input_tokens", usage.input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", usage.output_tokens)
            if choice.get("finish_reason"):
                span.set_attribute("gen_ai.response.finish_reasons", [str(choice["finish_reason"])])
            return LLMResult(
                text=text,
                model=str(data.get("model") or self._model),
                usage=usage,
                finish_reason=choice.get("finish_reason"),
                latency_ms=latency,
            )

    async def stream(
        self, messages: list[LLMMessage], *, temperature: float | None = None, max_tokens: int | None = None
    ) -> AsyncIterator[str]:
        payload = self._payload(messages, temperature, max_tokens, stream=True)
        try:
            async with self._client.stream("POST", "/chat/completions", json=payload) as response:
                if response.status_code >= 400:
                    raise LLMError(
                        f"Inference server error {response.status_code}", retryable=response.status_code in RETRYABLE_STATUS
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    delta = (json.loads(chunk).get("choices") or [{}])[0].get("delta", {}).get("content")
                    if delta:
                        yield delta
        except httpx.HTTPError as exc:
            raise LLMError("Inference server unreachable", retryable=True) from exc

    async def structured_output(
        self,
        messages: list[LLMMessage],
        schema: type[T],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_schema: dict | None = None,
    ) -> StructuredResult[T]:
        """Constrained JSON generation + validation, with one repair round on invalid output."""
        target_schema = json_schema or schema.model_json_schema()
        validator = Draft202012Validator(target_schema) if json_schema else None
        params = self._structured_params(schema.__name__, target_schema)
        conversation = list(messages)
        usage = TokenUsage()
        latency = 0.0
        last_error = ""
        budget = max_tokens or self.default_max_tokens
        for attempt in range(2):
            result = await self.generate(
                conversation, temperature=0.0 if temperature is None else temperature, max_tokens=budget, **params
            )
            usage = usage.add(result.usage)
            latency += result.latency_ms
            if result.finish_reason in TRUNCATED:
                # Cut off by the token budget: the JSON is incomplete (or empty for a tool call). Asking the model
                # to "repair" it with the same budget fails the same way, so retry once with a larger budget.
                last_error = f"output truncated at {budget} tokens"
                budget = min(budget * 2, MAX_STRUCTURED_TOKENS)
                conversation = list(messages)
                continue
            try:
                raw = extract_json(result.text)
                if validator is not None:
                    errors = sorted(validator.iter_errors(raw), key=lambda e: list(e.path))
                    if errors:
                        raise ValueError("; ".join(f"{'/'.join(map(str, e.path)) or '$'}: {e.message}" for e in errors[:5]))
                value = schema.model_validate(raw)
                return StructuredResult(value=value, model=result.model, usage=usage, latency_ms=latency, repaired=attempt > 0)
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                last_error = str(exc)[:800]
                conversation = [
                    *messages,
                    LLMMessage(role="assistant", content=result.text[:4000]),
                    LLMMessage(
                        role="user",
                        content=(
                            "Your previous answer was not valid for the required JSON schema: "
                            f"{last_error}\nReturn only the corrected JSON object."
                        ),
                    ),
                ]
        raise LLMError(f"The model did not return valid structured output: {last_error[:300]}", retryable=True)
