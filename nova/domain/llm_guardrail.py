"""Outbound guardrail: what classification of content may be sent to which model (same triplet as ORBIT's).

* Content above the *ceiling* (``NOVA_LLM_MAX_CLASSIFICATION``, default C1) is never sent to an external model.
  A destination declared local (``NOVA_LLM_LOCAL``, or a host listed in ``NOVA_LLM_LOCAL_HOSTS``) lifts the ceiling:
  the data stays inside the organization's perimeter.
* An unknown level is read as C3. A refused call raises ``ClassificationBlocked`` (explicit, non-retryable, no
  fallback model, nothing is sent): never a silent send.
* ``prepare`` masks personal data and secrets in what leaves for an external model.

The level of a call is a ``CallScope``: the highest classification of everything the run has read so far (retrieved
context, stored extracts, Artifacts). It only goes up, so a run that touched C3 stays C3 for its remaining calls.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from nova.domain.enums import CLASSIFICATION_LABELS
from nova.domain.llm import LLMError

MAX_LEVEL = 3
REASON_CLASSIFICATION = "classification"
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

#: In-process view of ``nova_llm_guardrail_skips_total{reason}`` (tests, diagnostics); the OTel counter mirrors it.
SKIPS: Counter[str] = Counter()


@dataclass(frozen=True, slots=True)
class Destination:
    """Where a model call goes: ``local`` means inside the organization's perimeter."""

    name: str
    local: bool


@dataclass(slots=True)
class CallScope:
    """Highest classification (C0-C3) a run has read so far."""

    level: int = 0
    sources: set[str] = field(default_factory=set)  # what raised it (labels only, never content)

    def raise_to(self, level: int | None, source: str = "") -> None:
        value = MAX_LEVEL if level is None else max(0, min(MAX_LEVEL, int(level)))
        if value > self.level:
            self.level = value
        if value and source:
            self.sources.add(source)


class ClassificationBlocked(LLMError):
    """The call would send content above the destination's ceiling: refused, nothing left the platform."""

    def __init__(self, level: int, ceiling_: int, destination: str) -> None:
        label = CLASSIFICATION_LABELS.get(level, f"C{level}")
        super().__init__(
            f"This request uses {label} material, which may not be sent to the external model “{destination}” "
            f"(limit: C{ceiling_}). Use an internal model, or remove the restricted sources.",
            retryable=False,
        )
        self.level, self.ceiling, self.destination = level, ceiling_, destination


def ceiling(max_classification: int, *, local: bool) -> int:
    """Highest level that may be sent to a destination."""
    return MAX_LEVEL if local else max(0, min(MAX_LEVEL, int(max_classification)))


def allows(level: int | None, *, max_classification: int, local: bool) -> bool:
    """``True`` when content of this level may be sent (unknown level: treated as C3)."""
    value = MAX_LEVEL if level is None else int(level)
    return value <= ceiling(max_classification, local=local)


def record_skip(reason: str = REASON_CLASSIFICATION, count: int = 1) -> None:
    if count > 0:
        SKIPS[reason] += count


def skip_count(reason: str = REASON_CLASSIFICATION) -> int:
    return SKIPS[reason]


_PII = [
    ("SECRET", re.compile(r"\b(?:orb|fgk)_[A-Za-z0-9]{6,}_[A-Za-z0-9]{16,}\b")),
    ("SECRET", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("SECRET", re.compile(r"(?i)\b(?:bearer|api[_-]?key|password|secret|token)\s*[:=]\s*\S+")),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,3})?\b")),
    ("PHONE", re.compile(r"(?:\+\d{1,3}[\s.-]?\d(?:[\s.-]?\d{2}){4}\b|\b0\d(?:[\s.-]?\d{2}){4}\b)")),
]


def prepare(text: str) -> str:
    """Text as it may leave for an external model: secrets, e-mail addresses, IBANs and phone numbers masked."""
    for label, pattern in _PII:
        text = pattern.sub(f"[{label}]", text)
    return text
