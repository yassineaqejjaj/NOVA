"""Per-call model records: cost from configured prices, recording never breaks the call."""

from __future__ import annotations

import pytest

from nova.agent.providers.recording import CallRecord, RecordingProvider
from nova.domain.llm import LLMError, LLMMessage, LLMResult
from nova.domain.outputs import TokenUsage
from nova.domain.pricing import Pricing


class _Inner:
    model_name = "m1"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def generate(self, messages, *, temperature=None, max_tokens=None):
        if self.fail:
            raise LLMError("boom", retryable=True)
        return LLMResult(
            text="ok", model="m1", usage=TokenUsage(input_tokens=2000, output_tokens=500, model_calls=1), latency_ms=12.0
        )

    async def stream(self, messages, *, temperature=None, max_tokens=None):
        for part in ("a", "b"):
            yield part


MSG = [LLMMessage(role="user", content="hi")]


def test_pricing_uses_the_model_entry_then_the_global_price():
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=500_000)
    assert Pricing().estimate("m", usage) == 0.0  # self-hosted default
    assert Pricing(1.0, 2.0).estimate("m", usage) == 2.0
    assert Pricing(1.0, 2.0, {"m": (3.0, 4.0)}).estimate("m", usage) == 5.0
    assert Pricing(1.0, 2.0, {"m": (3.0, 4.0)}).estimate("other", usage) == 2.0


async def test_generate_is_recorded_with_cost_and_latency():
    seen: list[CallRecord] = []

    async def record(rec):
        seen.append(rec)

    provider = RecordingProvider(_Inner(), record, Pricing(1000.0, 2000.0))
    result = await provider.generate(MSG)
    assert result.text == "ok" and provider.model_name == "m1"
    (rec,) = seen
    assert (rec.kind, rec.model, rec.status, rec.latency_ms) == ("generate", "m1", "ok", 12.0)
    assert rec.cost_usd == pytest.approx(3.0)  # (2000*1000 + 500*2000) / 1e6


async def test_failures_are_recorded_and_reraised_and_stream_has_no_usage():
    seen: list[CallRecord] = []

    async def record(rec):
        seen.append(rec)

    provider = RecordingProvider(_Inner(fail=True), record, Pricing())
    with pytest.raises(LLMError):
        await provider.generate(MSG)
    assert seen[-1].status == "error" and seen[-1].error == "LLMError" and seen[-1].usage is None
    chunks = [c async for c in provider.stream(MSG)]
    assert chunks == ["a", "b"] and seen[-1].kind == "stream" and seen[-1].usage is None


async def test_a_recorder_failure_never_fails_the_call():
    async def broken(rec):
        raise RuntimeError("db down")

    provider = RecordingProvider(_Inner(), broken, Pricing())
    assert (await provider.generate(MSG)).text == "ok"
