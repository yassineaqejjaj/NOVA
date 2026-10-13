"""Outbound guardrail: nothing above the ceiling reaches an external model (synthetic content only)."""

from __future__ import annotations

import pytest

from nova.agent.providers.guard import GuardedProvider
from nova.config import Settings
from nova.domain.llm import LLMMessage, LLMResult
from nova.domain.llm_guardrail import (
    CallScope,
    ClassificationBlocked,
    Destination,
    allows,
    ceiling,
    prepare,
    skip_count,
)
from nova.domain.outputs import IntentClassification

EXTERNAL = Destination("anthropic/test", local=False)
INTERNAL = Destination("vllm/test", local=True)


class Spy:
    """A model that records what it is sent: the assertions are about what *left* the platform."""

    model_name = "spy"

    def __init__(self) -> None:
        self.sent: list[list[LLMMessage]] = []

    async def generate(self, messages, **kwargs):
        self.sent.append(messages)
        return LLMResult(text="ok", model="spy")

    async def structured_output(self, messages, schema, **kwargs):
        self.sent.append(messages)
        raise AssertionError("not used")

    async def stream(self, messages, **kwargs):
        self.sent.append(messages)
        yield "ok"


def guarded(spy: Spy, level: int, destination: Destination = EXTERNAL, **kwargs) -> GuardedProvider:
    return GuardedProvider(spy, CallScope(level), destination, max_classification=1, **kwargs)


def test_ceiling_and_allows_follow_the_destination():
    assert [allows(n, max_classification=1, local=False) for n in (0, 1, 2, 3)] == [True, True, False, False]
    assert all(allows(n, max_classification=1, local=True) for n in (0, 1, 2, 3))  # internal model: not capped
    assert allows(None, max_classification=1, local=False) is False  # unknown level is read as C3
    assert allows(None, max_classification=3, local=False) is True
    assert ceiling(2, local=False) == 2 and ceiling(0, local=True) == 3


def test_scope_only_goes_up_and_unknown_is_c3():
    scope = CallScope()
    scope.raise_to(2)
    scope.raise_to(1)
    assert scope.level == 2
    scope.raise_to(None)
    assert scope.level == 3


def test_prepare_masks_secrets_and_personal_data():
    text = prepare("Mail jane.doe@example.org, IBAN FR7630006000011234567890189, token: abc123secret, call +33 1 23 45 67 89")
    assert "jane.doe" not in text and "FR7630006000011234567890189" not in text and "abc123secret" not in text
    assert "[EMAIL]" in text and "[IBAN]" in text and "[SECRET]" in text and "[PHONE]" in text
    assert prepare("Plain product requirements, 12 users") == "Plain product requirements, 12 users"


@pytest.mark.parametrize("level", [2, 3])
async def test_content_above_the_ceiling_is_never_sent_to_an_external_model(level):
    spy, blocked = Spy(), []
    before = skip_count()
    model = guarded(spy, level, on_block=lambda error, name: blocked.append((error.level, error.destination, name)))
    messages = [LLMMessage(role="user", content="Synthetic restricted note")]
    with pytest.raises(ClassificationBlocked) as refused:
        await model.generate(messages)
    with pytest.raises(ClassificationBlocked):
        await model.structured_output(messages, IntentClassification)
    with pytest.raises(ClassificationBlocked):
        _ = [chunk async for chunk in model.stream(messages)]
    assert spy.sent == []  # no request left, whatever the entry point
    assert refused.value.retryable is False and f"C{level}" in str(refused.value) and "internal model" in str(refused.value)
    assert blocked[0] == (level, "anthropic/test", "spy") and skip_count() == before + 3


async def test_content_within_the_ceiling_goes_out_masked():
    spy = Spy()
    await guarded(spy, 1).generate([LLMMessage(role="user", content="Ask jane.doe@example.org about the roadmap")])
    assert spy.sent[0][0].content == "Ask [EMAIL] about the roadmap"
    spy = Spy()
    await guarded(spy, 1, redact_pii=False).generate([LLMMessage(role="user", content="jane.doe@example.org")])
    assert spy.sent[0][0].content == "jane.doe@example.org"


async def test_an_internal_model_receives_c3_untouched():
    spy = Spy()
    await guarded(spy, 3, INTERNAL).generate([LLMMessage(role="user", content="jane.doe@example.org C3 note")])
    assert spy.sent[0][0].content == "jane.doe@example.org C3 note"


async def test_a_failing_audit_hook_never_lets_the_call_through():
    spy = Spy()

    def broken(error, name):
        raise RuntimeError("audit store down")

    with pytest.raises(ClassificationBlocked):
        await guarded(spy, 3, on_block=broken).generate([LLMMessage(role="user", content="x")])
    assert spy.sent == []


def test_which_endpoints_are_internal():
    default = Settings(_env_file=None)
    assert default.llm_max_classification == 1 and default.llm_is_local  # the default vLLM runs on localhost
    assert not Settings(llm_provider="anthropic", _env_file=None).llm_is_local
    assert not Settings(
        llm_provider="openai_compatible", llm_base_url="https://api.vendor.example/v1", _env_file=None
    ).llm_is_local
    declared = Settings(llm_provider="anthropic", llm_local=True, _env_file=None)
    assert declared.llm_is_local
    listed = Settings(
        llm_provider="openai_compatible", llm_base_url="http://gpu.corp.example/v1", llm_local_hosts="gpu.corp.example"
    )
    assert listed.llm_is_local and listed.is_local_host("http://GPU.corp.example:8000/v1")
    assert not listed.is_local_host("https://other.example/v1")


def test_production_refuses_a_ceiling_above_c1_on_an_external_model_without_an_explicit_override():
    prod = {
        "env": "production",
        "auth_mode": "oidc",
        "public_url": "https://nova.example",
        "cookie_secure": True,
        "session_secret": "s" * 40,
        "secrets_key": "k" * 40,
        "forge_inbound_token": "f" * 40,
        "oidc_client_secret": "o" * 20,
        "llm_provider": "anthropic",
        "llm_api_key": "not-a-real-key",
        "_env_file": None,
    }
    assert Settings(**prod).llm_max_classification == 1  # C1 on an external model: fine
    with pytest.raises(ValueError, match="NOVA_LLM_MAX_CLASSIFICATION"):
        Settings(**prod, llm_max_classification=3)
    assert Settings(**prod, llm_max_classification=3, llm_local=True).llm_max_classification == 3  # declared internal
    assert Settings(**prod, llm_max_classification=3, llm_allow_classified_external=True)  # explicit override
