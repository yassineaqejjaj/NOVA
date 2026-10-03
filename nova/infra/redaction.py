"""PII and secret redaction for logs, telemetry and stored tool I/O (configurable patterns)."""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any

from nova.config import get_settings

BUILTIN = [
    ("SECRET", r"\b(?:orb|fgk)_[A-Za-z0-9]{6,}_[A-Za-z0-9]{16,}\b"),  # ORBIT / FORGE keys
    ("SECRET", r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),  # JWT
    ("SECRET", r"(?i)\b(?:bearer|api[_-]?key|password|secret|token)\s*[:=]\s*\S+"),
    ("EMAIL", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ("IBAN", r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\b"),
    ("CARD", r"\b(?:\d[ -]?){13,19}\b"),
    ("PHONE", r"(?:\+\d{1,3}[\s.-]?\d(?:[\s.-]?\d{2}){4}\b|\b0\d(?:[\s.-]?\d{2}){4}\b)"),
]


@lru_cache
def _patterns() -> list[tuple[str, re.Pattern[str]]]:
    extra = [p.strip() for p in get_settings().redact_patterns.split(",") if p.strip()]
    return [(label, re.compile(p)) for label, p in BUILTIN] + [("REDACTED", re.compile(p)) for p in extra]


def redact(text: str) -> str:
    for label, pattern in _patterns():
        text = pattern.sub(f"[{label}]", text)
    return text


def redact_obj(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return value
    if isinstance(value, str):
        return redact(value) if len(value) < 20000 else redact(value[:20000])
    if isinstance(value, dict):
        return {
            k: (
                "[SECRET]"
                if str(k).lower() in {"password", "token", "api_key", "secret", "authorization"}
                else redact_obj(v, depth + 1)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_obj(v, depth + 1) for v in value]
    return value


class RedactingFilter(logging.Filter):
    """Logging filter: never log secrets or personal data."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = (
                tuple(redact(a) if isinstance(a, str) else a for a in record.args)
                if isinstance(record.args, tuple)
                else record.args
            )
        return True
