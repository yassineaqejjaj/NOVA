"""Budget guard: a call that would go over a limit never starts."""

from __future__ import annotations

import pytest

from nova.agent.providers.budget import BudgetedProvider, BudgetExceeded
from nova.agent.providers.fallback import Breaker, FallbackProvider
from nova.domain.llm import LLMMessage, LLMResult

MSG = [LLMMessage(role="user", content="hi")]


class Model:
    def __init__(self, name="m") -> None:
        self.model_name, self.calls = name, 0

    async def generate(self, messages, **kw):
        self.calls += 1
        return LLMResult(text="ok", model=self.model_name)

    async def structured_output(self, messages, schema, **kw):
        self.calls += 1
        raise NotImplementedError

    async def stream(self, messages, **kw):
        self.calls += 1
        yield "a"


async def test_calls_pass_until_the_check_refuses_and_then_never_reach_the_model():
    model, state = Model(), {"stop": False}

    async def check():
        if state["stop"]:
            raise BudgetExceeded("run", "This task reached its cost limit ($1).")

    provider = BudgetedProvider(model, check)
    assert (await provider.generate(MSG)).text == "ok" and provider.model_name == "m"
    state["stop"] = True
    with pytest.raises(BudgetExceeded, match="cost limit") as raised:
        await provider.generate(MSG)
    with pytest.raises(BudgetExceeded):
        [c async for c in provider.stream(MSG)]
    assert model.calls == 1 and raised.value.retryable is False and raised.value.scope == "run"


async def test_a_refused_budget_is_not_retried_on_a_fallback_model():
    async def refuse():
        raise BudgetExceeded("user", "usage limit")

    main, backup = Model("main"), Model("backup")
    provider = FallbackProvider(
        [BudgetedProvider(main, refuse), BudgetedProvider(backup, refuse)],
        {"main": Breaker(3, 60), "backup": Breaker(3, 60)},
    )
    with pytest.raises(BudgetExceeded):
        await provider.generate(MSG)
    assert main.calls == 0 and backup.calls == 0
