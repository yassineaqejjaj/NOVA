"""Model fallback with a circuit breaker (self-healing for inference outages).

Providers are tried in order. A *transient* failure (``LLMError(retryable=True)``, a timeout or a connection
error) moves on to the next one; a non-retryable ``LLMError`` (bad request, content refused) is raised as it is:
another model would not fix it. After ``threshold`` consecutive failures a provider is skipped for ``cooldown``
seconds (circuit open), then given one probing call (half-open). When every provider is skipped or failing, the
last error is raised so the execution's normal retry / failure handling applies.

Fallback only ever covers the organization's own provider: a user's own key (bring your own model) never falls
back to another provider, so their data is not sent somewhere they did not choose.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from nova.domain.llm import LLMError, LLMMessage, LLMProvider, LLMResult, StructuredResult, T

log = logging.getLogger(__name__)
TRANSIENT = (LLMError, ConnectionError, TimeoutError, OSError)


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, LLMError):
        return exc.retryable
    return isinstance(exc, ConnectionError | TimeoutError | OSError)


@dataclass
class Breaker:
    threshold: int
    cooldown: float
    failures: int = 0
    opened_at: float | None = None

    def allows(self, now: float) -> bool:
        if self.opened_at is None:
            return True
        return now - self.opened_at >= self.cooldown  # half-open: one probing call

    def success(self) -> None:
        self.failures, self.opened_at = 0, None

    def failure(self, now: float) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = now  # (re)open; a failed probe restarts the cooldown

    @property
    def is_open(self) -> bool:
        return self.opened_at is not None


_BREAKERS: dict[str, Breaker] = {}  # shared by every execution of the process: an outage is seen by all


def fallback_breakers(providers: list[LLMProvider], settings: Any) -> dict[str, Breaker]:
    """One breaker per model, created on first use with the configured threshold and cooldown."""
    for provider in providers:
        _BREAKERS.setdefault(provider.model_name, Breaker(settings.llm_circuit_failures, settings.llm_circuit_cooldown_seconds))
    return _BREAKERS


FallbackHook = Callable[[str, str, BaseException], Awaitable[None] | None]


class FallbackProvider:
    def __init__(
        self,
        providers: list[LLMProvider],
        breakers: dict[str, Breaker],
        *,
        on_fallback: FallbackHook | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not providers:
            raise ValueError("FallbackProvider needs at least one provider")
        self._providers, self._breakers, self._on_fallback, self._clock = providers, breakers, on_fallback, clock

    @property
    def model_name(self) -> str:
        return self._providers[0].model_name

    def _breaker(self, provider: LLMProvider) -> Breaker:
        return self._breakers[provider.model_name]

    async def _notify(self, failed: LLMProvider, nxt: LLMProvider | None, exc: BaseException) -> None:
        log.warning(
            "Model %s failed (%s); %s", failed.model_name, exc, f"falling back to {nxt.model_name}" if nxt else "no fallback left"
        )
        if self._on_fallback and nxt is not None:
            result = self._on_fallback(failed.model_name, nxt.model_name, exc)
            if result is not None:
                await result

    async def _run[R](self, call: Callable[[LLMProvider], Awaitable[R]]) -> R:
        last: BaseException | None = None
        candidates = [p for p in self._providers if self._breaker(p).allows(self._clock())]
        if not candidates:  # everything is cooling down: probe the primary rather than fail without trying
            candidates = self._providers[:1]
        for index, provider in enumerate(candidates):
            try:
                result = await call(provider)
            except TRANSIENT as exc:
                if not is_transient(exc):
                    raise
                self._breaker(provider).failure(self._clock())
                last = exc
                await self._notify(provider, candidates[index + 1] if index + 1 < len(candidates) else None, exc)
                continue
            self._breaker(provider).success()
            return result
        assert last is not None
        raise last

    async def generate(
        self, messages: list[LLMMessage], *, temperature: float | None = None, max_tokens: int | None = None
    ) -> LLMResult:
        return await self._run(lambda p: p.generate(messages, temperature=temperature, max_tokens=max_tokens))

    async def structured_output(
        self,
        messages: list[LLMMessage],
        schema: type[T],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_schema: dict | None = None,
    ) -> StructuredResult[T]:
        return await self._run(
            lambda p: p.structured_output(
                messages, schema, temperature=temperature, max_tokens=max_tokens, json_schema=json_schema
            )
        )

    async def stream(
        self, messages: list[LLMMessage], *, temperature: float | None = None, max_tokens: int | None = None
    ) -> AsyncIterator[str]:
        """Falls back only before the first chunk: once text reached the user, a half answer cannot be swapped."""
        last: BaseException | None = None
        candidates = [p for p in self._providers if self._breaker(p).allows(self._clock())] or self._providers[:1]
        for index, provider in enumerate(candidates):
            started = False
            try:
                async for chunk in provider.stream(messages, temperature=temperature, max_tokens=max_tokens):
                    started = True
                    yield chunk
            except TRANSIENT as exc:
                if not is_transient(exc):
                    raise
                self._breaker(provider).failure(self._clock())
                if started:  # text already reached the caller: report the failure instead of swapping the answer
                    raise
                last = exc
                await self._notify(provider, candidates[index + 1] if index + 1 < len(candidates) else None, exc)
                continue
            self._breaker(provider).success()
            return
        assert last is not None
        raise last
