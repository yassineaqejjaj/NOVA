"""Classification guard of what NOVA captures into FORGE (default ceiling C1, ``NOVA_FORGE_MAX_CAPTURE_CLASSIFICATION``).

Capture by re-execution sends the request and context excerpts so FORGE can replay them: above the ceiling that text
must not leave NOVA, so the run is not captured and says why. Observed capture sends outcomes only; above the ceiling
it also withholds the request text, even when the organization opted in to send it.
"""

from __future__ import annotations

from nova.domain.evaluation import ExecutionRecord

SECRET = 3  # a document without a level is read as secret (fail closed)


def capture_level(record: ExecutionRecord) -> int:
    """The highest classification among the context documents and the recorded maximum."""
    levels = [record.context_max_classification]
    levels += [SECRET if d.get("classification") is None else int(d["classification"]) for d in record.context_documents]
    return max(levels)


def above_ceiling(record: ExecutionRecord, ceiling: int) -> int | None:
    """The classification that exceeds ``ceiling``, ``None`` when the run may be captured."""
    level = capture_level(record)
    return level if level > ceiling else None


def not_captured_note(level: int, ceiling: int) -> str:
    return f"Not captured: classification C{level} is above the C{ceiling} ceiling for FORGE capture"
