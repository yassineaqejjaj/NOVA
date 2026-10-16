"""Classification guard: refuse, before the call, to send content above the ceiling to an external model.

A decorator over any ``LLMProvider`` (same shape as ``BudgetedProvider``). The level of the call is the run's
``CallScope`` (domain/llm_guardrail.py); a refused call raises ``ClassificationBlocked``: non-retryable, so no retry
and no fallback model, and nothing leaves the platform. Every refusal is counted and reported to ``on_block``
(audit event with the reason, never the content). For an external destination the messages are masked first.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from opentelemetry import metrics

from nova.domain.llm import LLMMessage, LLMProvider, LLMResult, StructuredResult, T
from nova.domain.llm_guardrail import (
    REASON_CLASSIFICATION,
    CallScope,
    ClassificationBlocked,
    Destination,
    allows,
    ceiling,
    prepare,
    record_skip,
)

log = logging.getLogger(__name__)
_SKIPS = metrics.get_meter("nova.llm").create_counter(
    "nova_llm_guardrail_skips_total", description="Model calls refused by the classification guardrail, by reason"
)

BlockHook = Callable[[ClassificationBlocked, str], Awaitable[None] | None]


class GuardedProvider:
    def __init__(
        self,
        inner: LLMProvider,
        scope: CallScope,
        destination: Destination,
        *,
        max_classification: int,
        redact_pii: bool = True,
        on_block: BlockHook | None = None,
    ) -> None:
        self._inner, self._scope, self._destination = inner, scope, destination
        self._max, self._redact, self._on_block = max_classification, redact_pii, on_block

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    async def _check(self) -> None:
        level = self._scope.level
        if allows(level, max_classification=self._max, local=self._destination.local):
            return
        record_skip(REASON_CLASSIFICATION)
        _SKIPS.add(1, {"reason": REASON_CLASSIFICATION})
        error = ClassificationBlocked(level, ceiling(self._max, local=False), self._destination.name)
        log.warning("Model call to %s refused: C%d content, ceiling C%d", self._destination.name, level, error.ceiling)
        if self._on_block is not None:
            try:
                result = self._on_block(error, self._inner.model_name)
                if result is not None:
                    await result
            except Exception:  # the refusal stands even when the audit record cannot be written
                log.warning("Guardrail refusal could not be recorded", exc_info=True)
        raise error

    def _prepare(self, messages: list[LLMMessage]) -> list[LLMMessage]:
        if self._destination.local or not self._redact:
            return messages
        return [m.model_copy(update={"content": prepare(m.content)}) for m in messages]

    async def generate(
        self, messages: list[LLMMessage], *, temperature: float | None = None, max_tokens: int | None = None
    ) -> LLMResult:
        await self._check()
        return await self._inner.generate(self._prepare(messages), temperature=temperature, max_tokens=max_tokens)

    async def structured_output(
        self,
        messages: list[LLMMessage],
        schema: type[T],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_schema: dict | None = None,
    ) -> StructuredResult[T]:
        await self._check()
        return await self._inner.structured_output(
            self._prepare(messages), schema, temperature=temperature, max_tokens=max_tokens, json_schema=json_schema
        )

    async def stream(
        self, messages: list[LLMMessage], *, temperature: float | None = None, max_tokens: int | None = None
    ) -> AsyncIterator[str]:
        await self._check()
        async for chunk in self._inner.stream(self._prepare(messages), temperature=temperature, max_tokens=max_tokens):
            yield chunk
