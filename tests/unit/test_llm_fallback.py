"""Model fallback and circuit breaker (self-healing for inference outages)."""

from __future__ import annotations

import pytest

from nova.agent.providers.fallback import Breaker, FallbackProvider
from nova.domain.llm import LLMError, LLMMessage, LLMResult
from nova.domain.outputs import TokenUsage

MSG = [LLMMessage(role="user", content="hi")]


class Model:
    def __init__(self, name: str, error: BaseException | None = None, chunks: tuple[str, ...] = ("a", "b")) -> None:
        self.model_name, self.error, self.chunks, self.calls = name, error, chunks, 0

    async def generate(self, messages, *, temperature=None, max_tokens=None):
        self.calls += 1
        if self.error:
            raise self.error
        return LLMResult(text=self.model_name, model=self.model_name, usage=TokenUsage())

    async def structured_output(self, messages, schema, **kw):
        raise NotImplementedError

    async def stream(self, messages, *, temperature=None, max_tokens=None):
        self.calls += 1
        for i, chunk in enumerate(self.chunks):
            if self.error and i == len(self.chunks) - 1 and kw_mid(self):
                raise self.error
            yield chunk
        if self.error and not kw_mid(self):
            raise self.error


def kw_mid(model: Model) -> bool:
    return getattr(model, "fail_midway", False)


class Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


def build(*models: Model, threshold: int = 2, cooldown: float = 30.0, hook=None):
    clock = Clock()
    breakers = {m.model_name: Breaker(threshold, cooldown) for m in models}
    return FallbackProvider(list(models), breakers, on_fallback=hook, clock=clock), breakers, clock


async def test_a_transient_failure_falls_back_and_reports_it():
    seen = []
    primary = Model("main", LLMError("overloaded", retryable=True))
    backup = Model("backup")

    async def hook(failed, nxt, exc):
        seen.append((failed, nxt))

    provider, _, _ = build(primary, backup, hook=hook)
    assert (await provider.generate(MSG)).text == "backup"
    assert seen == [("main", "backup")] and primary.calls == 1 and backup.calls == 1


async def test_connection_errors_and_timeouts_count_as_transient():
    for error in (ConnectionError("down"), TimeoutError("slow")):
        provider, _, _ = build(Model("main", error), Model("backup"))
        assert (await provider.generate(MSG)).text == "backup"


async def test_a_non_retryable_error_is_raised_untouched():
    primary, backup = Model("main", LLMError("bad request", retryable=False)), Model("backup")
    provider, breakers, _ = build(primary, backup)
    with pytest.raises(LLMError, match="bad request"):
        await provider.generate(MSG)
    assert backup.calls == 0 and breakers["main"].failures == 0  # not an outage


async def test_the_circuit_opens_after_repeated_failures_then_probes_after_the_cooldown():
    primary, backup = Model("main", LLMError("down", retryable=True)), Model("backup")
    provider, breakers, clock = build(primary, backup, threshold=2, cooldown=30)
    await provider.generate(MSG)
    await provider.generate(MSG)
    assert breakers["main"].is_open and primary.calls == 2
    await provider.generate(MSG)  # circuit open: the primary is not even tried
    assert primary.calls == 2 and backup.calls == 3
    clock.now = 31.0  # cooldown over: one probing call
    primary.error = None
    assert (await provider.generate(MSG)).text == "main"
    assert not breakers["main"].is_open and breakers["main"].failures == 0


async def test_when_every_model_fails_the_last_error_is_raised():
    provider, _, _ = build(Model("main", LLMError("a", retryable=True)), Model("backup", LLMError("b", retryable=True)))
    with pytest.raises(LLMError, match="b"):
        await provider.generate(MSG)


async def test_streams_fall_back_only_before_the_first_chunk():
    early = Model("main", LLMError("down", retryable=True), chunks=())
    provider, _, _ = build(early, Model("backup"))
    assert [c async for c in provider.stream(MSG)] == ["a", "b"]

    late = Model("main", LLMError("cut", retryable=True))
    late.fail_midway = True
    provider, _, _ = build(late, Model("backup"))
    got = []
    with pytest.raises(LLMError, match="cut"):
        async for chunk in provider.stream(MSG):
            got.append(chunk)
    assert got == ["a"]  # the partial answer is never mixed with another model's
