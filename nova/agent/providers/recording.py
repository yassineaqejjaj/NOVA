"""Record every model call of a run (tokens, cost, latency) without changing what the agents see.

A decorator over any ``LLMProvider``. Recording is best effort: a bookkeeping failure is logged and never
fails or slows the call's result. Prompts and answers are not stored here (they may carry C2/C3 context).
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from nova.domain.llm import LLMMessage, LLMProvider, LLMResult, StructuredResult, T
from nova.domain.outputs import TokenUsage
from nova.domain.pricing import Pricing

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CallRecord:
    kind: str
    model: str | None
    usage: TokenUsage | None
    cost_usd: float | None
    latency_ms: float
    status: str = "ok"
    error: str | None = None


Recorder = Callable[[CallRecord], Awaitable[None]]


class RecordingProvider:
    def __init__(self, inner: LLMProvider, record: Recorder, pricing: Pricing) -> None:
        self._inner, self._record, self._pricing = inner, record, pricing

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    async def _emit(self, rec: CallRecord) -> None:
        try:
            await self._record(rec)
        except Exception:
            log.warning("LLM call could not be recorded", exc_info=True)

    async def _timed[R: (LLMResult, StructuredResult)](self, kind: str, call: Callable[[], Awaitable[R]]) -> R:
        started = time.perf_counter()
        try:
            result = await call()
        except Exception as exc:
            latency = (time.perf_counter() - started) * 1000
            await self._emit(CallRecord(kind, self.model_name, None, None, latency, "error", type(exc).__name__))
            raise
        latency = result.latency_ms or (time.perf_counter() - started) * 1000
        cost = self._pricing.estimate(result.model, result.usage)
        await self._emit(CallRecord(kind, result.model, result.usage, cost, latency))
        return result

    async def generate(
        self, messages: list[LLMMessage], *, temperature: float | None = None, max_tokens: int | None = None
    ) -> LLMResult:
        return await self._timed(
            "generate", lambda: self._inner.generate(messages, temperature=temperature, max_tokens=max_tokens)
        )

    async def structured_output(
        self,
        messages: list[LLMMessage],
        schema: type[T],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_schema: dict | None = None,
    ) -> StructuredResult[T]:
        return await self._timed(
            "structured",
            lambda: self._inner.structured_output(
                messages, schema, temperature=temperature, max_tokens=max_tokens, json_schema=json_schema
            ),
        )

    async def stream(
        self, messages: list[LLMMessage], *, temperature: float | None = None, max_tokens: int | None = None
    ) -> AsyncIterator[str]:
        """Streams report no usage: the call is recorded with its latency and no token counts."""
        started = time.perf_counter()
        try:
            async for chunk in self._inner.stream(messages, temperature=temperature, max_tokens=max_tokens):
                yield chunk
        except Exception as exc:
            await self._emit(
                CallRecord(
                    "stream", self.model_name, None, None, (time.perf_counter() - started) * 1000, "error", type(exc).__name__
                )
            )
            raise
        await self._emit(CallRecord("stream", self.model_name, None, None, (time.perf_counter() - started) * 1000))
