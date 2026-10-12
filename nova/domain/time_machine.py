"""Time Machine: comparing a run with its what-if replays.

Pure rules (no I/O): how to pair the Artifacts two runs produced and how to express a change in cost or time.
"""

from __future__ import annotations


def relative_change(before: float | int | None, after: float | int | None) -> float | None:
    """``(after - before) / before``; ``None`` when either side is unknown or there is nothing to compare against."""
    if before is None or after is None or before == 0:
        return None
    return round((after - before) / before, 3)


def pair_by_type[T](left: list[tuple[str, T]], right: list[tuple[str, T]]) -> list[tuple[str, T | None, T | None]]:
    """Pair items of the same type in order of appearance; the leftovers of either side are paired with ``None``."""
    remaining: dict[str, list[T]] = {}
    for kind, item in right:
        remaining.setdefault(kind, []).append(item)
    pairs: list[tuple[str, T | None, T | None]] = []
    for kind, item in left:
        queue = remaining.get(kind) or []
        pairs.append((kind, item, queue.pop(0) if queue else None))
    for kind, queue in remaining.items():
        pairs.extend((kind, None, item) for item in queue)
    return pairs


def word_count(text: str) -> int:
    return len(text.split())
