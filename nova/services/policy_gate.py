"""Gate before a learned policy is activated: FORGE's out-of-production proof, ``NOVA_POLICY_GATE_MODE`` (docs/TRAINING.md).

``enforce`` holds a candidate that lacks proof (or whose proof cannot be fetched: fail-closed), ``warn`` records the
shortfall and lets the release go on, ``off`` does nothing. The proof comes from a ``ProofSource``: the training loop
derives it from its FORGE experiment; the SDLC agent's source is provided by FORGE's calibrated promotion gate
(``providers.policy_proof_source``, ``None`` until it exists: unavailable).
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from nova.config import get_settings
from nova.domain.policy_gate import GateDecision, Proof, decide
from nova.infra.models import AgentPolicy

log = logging.getLogger(__name__)


class ProofSource(Protocol):
    async def proof(self, candidate: AgentPolicy, baseline: AgentPolicy | None, lesson_sources: list[str]) -> Proof | None:
        """FORGE's evidence for the candidate (``None``: none yet). Raises when FORGE cannot answer."""
        ...


class PrecomputedProof:
    """A proof already in hand (the training loop's finished FORGE experiment)."""

    def __init__(self, proof: Proof) -> None:
        self._proof = proof

    async def proof(self, candidate: AgentPolicy, baseline: AgentPolicy | None, lesson_sources: list[str]) -> Proof | None:
        return self._proof


def mode() -> str:
    return get_settings().policy_gate_mode


async def evaluate(
    candidate: AgentPolicy,
    baseline: AgentPolicy | None,
    *,
    source: ProofSource | None,
    lesson_sources: list[str] | None = None,
) -> GateDecision:
    """Judge a candidate against the configured thresholds. Never raises: an unreachable FORGE is ``unavailable``."""
    settings = get_settings()
    if settings.policy_gate_mode == "off":
        return GateDecision(verdict="skipped", reasons=["garde désactivée (NOVA_POLICY_GATE_MODE=off)"])
    if source is None:
        return GateDecision(verdict="unavailable", reasons=["aucune source de preuve FORGE n'est configurée"])
    try:
        proof = await source.proof(candidate, baseline, list(lesson_sources or []))
    except Exception as exc:  # FORGE down or refusing: no proof is never a pass
        log.warning("Policy gate: FORGE proof unavailable for %s v%s: %s", candidate.agent, candidate.version, exc)
        return GateDecision(
            verdict="unavailable", reasons=[f"FORGE est injoignable ou a refusé la demande ({exc.__class__.__name__})"]
        )
    if proof is None:
        return GateDecision(verdict="insufficient", reasons=["FORGE n'a encore produit aucune preuve pour cette version"])
    return decide(proof, min_gain=settings.policy_gate_min_gain, min_evaluations=settings.policy_gate_min_evaluations)


def admits(decision: GateDecision) -> bool:
    """Whether the release may start: only ``enforce`` holds back a candidate that did not pass."""
    return decision.passed or get_settings().policy_gate_mode != "enforce"


def evidence_of(decision: GateDecision) -> dict[str, Any]:
    return {"mode": get_settings().policy_gate_mode, **decision.model_dump()}
