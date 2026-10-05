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
