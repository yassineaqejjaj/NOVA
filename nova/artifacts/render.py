"""Render structured Artifacts to Markdown (export, FORGE protocol output). Never parsed back."""

from __future__ import annotations

from typing import Any

from nova.domain.artifacts import ArtifactContent, ArtifactItem, ArtifactType, Citation, SectionContent
from nova.domain.enums import SectionKind

_PREFIX = {"heading": "### ", "bullet": "- ", "numbered": "1. ", "quote": "> ", "paragraph": ""}


def _cite(citations: list[Citation]) -> str:
    return "".join(f" [{c.label}]" for c in citations)


def _attr_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_attr_value(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_attr_value(v)}" for k, v in value.items())
    return str(value)


def _story_text(item: ArtifactItem) -> list[str]:
    a = item.attributes
    lines = []
    if a.get("as_a") and a.get("i_want"):
        line = f"  As a {a['as_a']}, I want {a['i_want']}"
        lines.append(line + (f", so that {a['so_that']}." if a.get("so_that") else "."))
    for ac in a.get("acceptance_criteria") or []:
        lines.append(f"  - Given {ac.get('given')}, when {ac.get('when')}, then {ac.get('then')}")
    return lines


def render_item(item: ArtifactItem, depth: int = 0) -> list[str]:
    pad = "  " * depth
    head = f"{pad}- **{item.title}**"
    if item.description:
        head += f" — {item.description}"
    lines = [head + _cite(item.citations)]
    if item.kind == "story":
        lines += [pad + line for line in _story_text(item)]
        skip = {"as_a", "i_want", "so_that", "acceptance_criteria"}
    else:
        skip = set()
    details = [f"{k.replace('_', ' ')}: {_attr_value(v)}" for k, v in item.attributes.items() if k not in skip]
    if details:
        lines.append(f"{pad}  _{' · '.join(details)}_")
    return lines


def render_section(section: SectionContent) -> list[str]:
    if section.kind == SectionKind.rich_text:
        return [_PREFIX.get(b.type, "") + b.text + _cite(b.citations) for b in section.blocks]
    ids = {i.id for i in section.items}
    children: dict[str | None, list[ArtifactItem]] = {}
    for item in section.items:
        parent = item.parent_id if item.parent_id in ids else None
        children.setdefault(parent, []).append(item)
    lines: list[str] = []

    def walk(parent: str | None, depth: int) -> None:
        for item in children.get(parent, []):
            lines.extend(render_item(item, depth))
            walk(item.id, depth + 1)

    walk(None, 0)
    return lines


def render_markdown(content: ArtifactContent, artifact_type: ArtifactType, *, sources: list[dict] | None = None) -> str:
    out = [f"# {content.title}", ""]
    for definition in artifact_type.sections:
        section = content.sections.get(definition.key)
        if section is None or section.is_empty():
            continue
        out += [f"## {definition.title}", "", *render_section(section), ""]
    if sources:
        out += ["## Sources", ""]
        out += [f"- [{s['label']}] {s['title']}" + (f" — {s['uri']}" if s.get("uri") else "") for s in sources]
    return "\n".join(out).rstrip() + "\n"
