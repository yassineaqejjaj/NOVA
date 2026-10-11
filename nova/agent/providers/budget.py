"""Budget guard: stop spending before a call that would go over a run's or a user's limit.

Checked *before* each model call, so a runaway workflow ends with a clear message instead of a surprise bill.
The check itself is injected (it reads what the run already cost); a refused call raises ``BudgetExceeded``,
a non-retryable ``LLMError``: no retry, no fallback model, the execution stops and keeps its completed steps.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable

from nova.domain.llm import LLMError, LLMMessage, LLMProvider, LLMResult, StructuredResult, T


class BudgetExceeded(LLMError):
    def __init__(self, scope: str, message: str) -> None:
        super().__init__(message, retryable=False)
        self.scope, self.message = scope, message  # scope: run | user


Check = Callable[[], Awaitable[None]]


class BudgetedProvider:
    def __init__(self, inner: LLMProvider, check: Check) -> None:
        self._inner, self._check = inner, check

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    async def generate(
        self, messages: list[LLMMessage], *, temperature: float | None = None, max_tokens: int | None = None
    ) -> LLMResult:
        await self._check()
        return await self._inner.generate(messages, temperature=temperature, max_tokens=max_tokens)

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
            messages, schema, temperature=temperature, max_tokens=max_tokens, json_schema=json_schema
        )

    async def stream(
        self, messages: list[LLMMessage], *, temperature: float | None = None, max_tokens: int | None = None
    ) -> AsyncIterator[str]:
        await self._check()
        async for chunk in self._inner.stream(messages, temperature=temperature, max_tokens=max_tokens):
            yield chunk
