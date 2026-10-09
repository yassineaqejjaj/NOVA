"""Anthropic provider: request shape, structured output through a forced tool call, streaming."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from nova.agent.providers.anthropic import STRUCTURED_TOOL, AnthropicProvider
from nova.domain.llm import LLMError, LLMMessage


class Answer(BaseModel):
    title: str
    score: int


def _provider(handler) -> AnthropicProvider:
    return AnthropicProvider("", "", api_key="sk-test", transport=httpx.MockTransport(handler))


async def test_generate_sends_system_separately_and_alternates_roles():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"model": "claude-sonnet-5-5", "content": [{"type": "text", "text": "Bonjour"}],
                                         "usage": {"input_tokens": 12, "output_tokens": 3}, "stop_reason": "end_turn"})  # fmt: skip

    result = await _provider(handler).generate(
        [
            LLMMessage(role="system", content="Be brief."),
            LLMMessage(role="user", content="Hi"),
            LLMMessage(role="user", content="FR please"),
        ]
    )
    assert result.text == "Bonjour" and result.usage.input_tokens == 12 and result.model == "claude-sonnet-5-5"
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "sk-test" and seen["headers"]["anthropic-version"]
    assert seen["body"]["system"] == "Be brief."
    assert seen["body"]["messages"] == [{"role": "user", "content": "Hi\n\nFR please"}]


async def test_structured_output_uses_a_forced_tool_and_validates():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tool_choice"] == {"type": "tool", "name": STRUCTURED_TOOL}
        assert body["tools"][0]["input_schema"]["properties"]["score"]["type"] == "integer"
        return httpx.Response(200, json={"content": [{"type": "tool_use", "name": STRUCTURED_TOOL, "input": {"title": "PRD", "score": 9}}],
                                         "usage": {"input_tokens": 5, "output_tokens": 5}})  # fmt: skip

    result = await _provider(handler).structured_output([LLMMessage(role="user", content="Rate it")], Answer)
    assert result.value == Answer(title="PRD", score=9)


async def test_streaming_yields_text_deltas_and_overload_is_retryable():
    events = [
        {"type": "message_start"},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Bon"}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "jour"}},
        {"type": "message_stop"},
    ]
    sse = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
    provider = _provider(lambda request: httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"}))
    assert "".join([chunk async for chunk in provider.stream([LLMMessage(role="user", content="Hi")])]) == "Bonjour"

    overloaded = _provider(lambda request: httpx.Response(529, json={"type": "error"}))
    with pytest.raises(LLMError) as exc:
        await overloaded.generate([LLMMessage(role="user", content="Hi")])
    assert exc.value.retryable


def test_missing_key_is_refused():
    with pytest.raises(LLMError):
        AnthropicProvider("", "", api_key="")


async def test_reasoning_budget_is_added_to_max_tokens_for_reasoning_models():
    from nova.agent.providers.openai_compatible import OpenAICompatibleProvider

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["max_tokens"] = json.loads(request.content)["max_tokens"]
        return httpx.Response(
            200, json={"model": "google/gemma-4-12b-qat", "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        )

    provider = OpenAICompatibleProvider(
        "http://lmstudio.test/v1",
        "google/gemma-4-12b-qat",
        default_max_tokens=4096,
        reasoning_tokens=2048,
        transport=httpx.MockTransport(handler),
    )
    assert (await provider.generate([LLMMessage(role="user", content="Hi")])).text == "ok"
    assert seen["max_tokens"] == 4096 + 2048


async def test_truncated_structured_output_retries_with_a_larger_budget():
    """A forced tool call cut off by max_tokens comes back as ``{}``: retry with twice the budget, not a "repair"."""
    budgets = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        budgets.append(body["max_tokens"])
        if len(budgets) == 1:
            return httpx.Response(200, json={"content": [{"type": "tool_use", "name": STRUCTURED_TOOL, "input": {}}],
                                             "usage": {"output_tokens": 4096}, "stop_reason": "max_tokens"})  # fmt: skip
        assert len(body["messages"]) == 1  # the truncated answer is not replayed
        return httpx.Response(200, json={"content": [{"type": "tool_use", "name": STRUCTURED_TOOL, "input": {"title": "PRD", "score": 9}}],
                                         "usage": {"output_tokens": 30}, "stop_reason": "tool_use"})  # fmt: skip

    provider = AnthropicProvider("", "", api_key="sk-test", default_max_tokens=4096, transport=httpx.MockTransport(handler))
    result = await provider.structured_output([LLMMessage(role="user", content="Rate it")], Answer)
    assert result.value.score == 9 and budgets == [4096, 8192]


async def test_models_that_reject_temperature_are_retried_without_it_and_remembered():
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "temperature" in body:
            return httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {"type": "invalid_request_error", "message": "`temperature` is deprecated for this model."},
                },
            )
        return httpx.Response(200, json={"model": "m", "content": [{"type": "text", "text": "OK"}], "usage": {}})

    provider = _provider(handler)
    assert (await provider.generate([LLMMessage(role="user", content="hi")])).text == "OK"
    assert "temperature" in bodies[0] and "temperature" not in bodies[1]
    await provider.generate([LLMMessage(role="user", content="again")])
    assert len(bodies) == 3 and "temperature" not in bodies[2]  # remembered: no more failing first attempt


async def test_models_that_cannot_be_forced_to_call_a_tool_get_an_instruction_instead():
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if body["tool_choice"]["type"] in ("tool", "any"):
            return httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": 'tool_choice: type "tool" and "any" are not supported for this model.',
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "model": "m",
                "content": [{"type": "tool_use", "name": STRUCTURED_TOOL, "input": {"title": "t", "score": 3}}],
                "usage": {},
            },
        )

    provider = _provider(handler)
    result = await provider.structured_output(
        [LLMMessage(role="system", content="Be exact."), LLMMessage(role="user", content="go")], Answer
    )
    assert result.value == Answer(title="t", score=3)
    assert bodies[0]["tool_choice"]["type"] == "tool" and bodies[1]["tool_choice"] == {"type": "auto"}
    assert "MUST answer by calling" in bodies[1]["system"] and bodies[1]["system"].startswith("Be exact.")
    await provider.structured_output([LLMMessage(role="user", content="again")], Answer)
    assert len(bodies) == 3 and bodies[2]["tool_choice"] == {"type": "auto"}  # remembered
