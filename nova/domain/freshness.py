"""Living Artifacts: is what an Artifact says still backed by its sources?

Pure rules (no I/O). An Artifact cites context items; ORBIT reports changes to documents and memory. An Artifact is
``stale`` when a change since its current version touched something it cites, ``fresh`` when none did, and
``unverified`` when there is nothing to check against (no citation, or ORBIT could not be asked) — never ``fresh`` by default.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

#: Changes that make a cited source worth re-reading.
IMPACTING_TYPES = ("document.new_version", "document.stale", "memory.superseded", "memory.conflict_detected")


@dataclass(frozen=True)
class CitedSource:
    ids: frozenset[str]  # every identifier the source is known by at ORBIT (document, memory item, chunk)
    title: str
    project_slug: str
    sections: frozenset[str]  # Artifact sections that cite it


@dataclass(frozen=True)
class SourceChange:
    id: str
    project_slug: str
    type: str
    type_label: str
    title: str
    target_id: str | None
    at: datetime


def assess(sources: list[CitedSource], changes: list[SourceChange], as_of: datetime, *, checked: bool = True) -> dict[str, Any]:
    """Compare the cited sources with the changes made after ``as_of``."""
    if not sources:
        return {"status": "unverified", "reason": "no_citations", "impacts": [], "stale_sections": []}
    if not checked:
        return {"status": "unverified", "reason": "context_unavailable", "impacts": [], "stale_sections": []}
    impacts = []
    for change in sorted(changes, key=lambda c: c.at, reverse=True):
        if change.at <= as_of or change.type not in IMPACTING_TYPES or not change.target_id:
            continue
        for source in sources:
            if source.project_slug == change.project_slug and change.target_id in source.ids:
                impacts.append(
                    {
                        "change_id": change.id,
                        "type": change.type,
                        "type_label": change.type_label,
                        "change_title": change.title,
                        "source_title": source.title,
                        "sections": sorted(source.sections),
                        "at": change.at.isoformat(),
                    }
                )
    stale = sorted({s for impact in impacts for s in impact["sections"]})
    return {
        "status": "stale" if impacts else "fresh",
        "reason": None,
        "impacts": impacts,
        "stale_sections": stale,
    }


def update_instruction(impacts: list[dict[str, Any]]) -> str:
    """The instruction given to the Artifact-edit Skill: what changed, so only that is revisited."""
    lines = ["Some sources this section cites have changed since it was written. Revisit only what these changes affect:"]
    seen: set[tuple[str, str]] = set()
    for impact in impacts:
        key = (impact["source_title"], impact["change_title"])
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {impact['source_title']}: {impact['type_label'] or impact['type']} — {impact['change_title']}")
    lines.append("Keep what is still correct, cite the updated sources, and say what you changed.")
    return "\n".join(lines)
