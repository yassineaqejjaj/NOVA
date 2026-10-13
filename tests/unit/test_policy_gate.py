"""The proof a learned policy must bring before activation: thresholds, independence, modes, fail-closed."""

from __future__ import annotations

import pytest

from nova.config import get_settings
from nova.domain.policy_gate import Proof, decide
from nova.infra.models import AgentPolicy
from nova.services import policy_gate


def proof(**kw) -> Proof:
    return Proof(
        **{
            "source": "fake",
            "validation_scenarios": ["a", "b", "c", "d"],
            "lesson_scenarios": ["z"],
            "gain": 0.05,
            "regressions": [],
            **kw,
        }
    )


def test_a_proof_with_gain_no_regression_and_enough_independent_evaluations_passes():
    decision = decide(proof(), min_gain=0.02, min_evaluations=3)
    assert decision.verdict == "passed" and decision.evaluations == 4 and decision.reasons == []


@pytest.mark.parametrize(
    ("changes", "needle"),
    [
        ({"gain": 0.01}, "gain"),
        ({"gain": None}, "non mesuré"),
        ({"gain": -0.2}, "gain"),
        ({"regressions": ["guard-1"]}, "régression"),
        ({"validation_scenarios": ["a", "b"]}, "2 évaluation(s) indépendante(s) sur 3"),
        ({"validation_scenarios": []}, "indépendant"),
    ],
)
def test_each_missing_condition_is_refused_and_named(changes, needle):
    decision = decide(proof(**changes), min_gain=0.02, min_evaluations=3)
    assert decision.verdict == "insufficient" and any(needle in r for r in decision.reasons)


def test_scenarios_the_lessons_come_from_do_not_count_as_validation():
    contaminated = proof(validation_scenarios=["a", "b", "c", "d"], lesson_scenarios=["a", "b", "c", "d"])
    decision = decide(contaminated, min_gain=0.02, min_evaluations=1)
    assert decision.verdict == "insufficient" and decision.evaluations == 0
    partly = proof(validation_scenarios=["a", "b", "c", "d"], lesson_scenarios=["a", "b"], runs_per_scenario=2)
    assert decide(partly, min_gain=0.02, min_evaluations=4).evaluations == 4  # only c and d, twice each


class Source:
    def __init__(self, result: Proof | None = None, error: Exception | None = None) -> None:
        self.result, self.error, self.calls = result, error, []

    async def proof(self, candidate, baseline, lesson_sources):
        self.calls.append(lesson_sources)
        if self.error:
            raise self.error
        return self.result


CANDIDATE = AgentPolicy(agent="sdlc", version=1)


@pytest.fixture
def settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "policy_gate_min_gain", 0.02)
    monkeypatch.setattr(s, "policy_gate_min_evaluations", 3)
    return s


async def test_a_fake_forge_that_cannot_answer_is_unavailable_never_a_pass(settings, monkeypatch):
    monkeypatch.setattr(settings, "policy_gate_mode", "enforce")
    down = Source(error=ConnectionError("FORGE unreachable"))
    decision = await policy_gate.evaluate(CANDIDATE, None, source=down, lesson_sources=["run-1"])
    assert decision.verdict == "unavailable" and "injoignable" in decision.reasons[0] and not policy_gate.admits(decision)
    assert down.calls == [["run-1"]]  # the source is told what the lessons were made from
    none = await policy_gate.evaluate(CANDIDATE, None, source=None)
    assert none.verdict == "unavailable" and not policy_gate.admits(none)
    assert (await policy_gate.evaluate(CANDIDATE, None, source=Source())).verdict == "insufficient"


async def test_modes_decide_whether_a_missing_proof_blocks(settings, monkeypatch):
    lacking = await policy_gate.evaluate(CANDIDATE, None, source=None)
    good = await policy_gate.evaluate(CANDIDATE, None, source=Source(proof()))
    assert good.verdict == "passed"
    for mode, blocks in (("enforce", True), ("warn", False)):
        monkeypatch.setattr(settings, "policy_gate_mode", mode)
        assert policy_gate.admits(lacking) is (not blocks) and policy_gate.admits(good)
    monkeypatch.setattr(settings, "policy_gate_mode", "off")
    skipped = await policy_gate.evaluate(CANDIDATE, None, source=None)
    assert skipped.verdict == "skipped" and policy_gate.admits(skipped)
