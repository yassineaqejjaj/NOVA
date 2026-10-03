"""Artifacts: structured, versioned product documents (docs/ARCHITECTURE.md §7).

An Artifact is a set of typed sections. ``rich_text`` sections hold a portable block model (the web
editor — Lexical — converts to and from it); ``items`` sections hold typed items (stories,
requirements, metrics…) whose ``attributes`` are validated against the item-kind JSON Schema.
Important state is never stored as free-form Markdown.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from nova.domain.enums import SectionKind

BlockKind = Literal["paragraph", "heading", "bullet", "numbered", "quote"]


class Citation(BaseModel):
    """Reference to a context item served to NOVA (validated at generation time)."""

    label: str  # label in the retrieval, e.g. "S2"
    ref: str | None = None  # context_retrieval_references.id
    title: str | None = None


class TextBlock(BaseModel):
    type: BlockKind = "paragraph"
    text: str = ""
    citations: list[Citation] = Field(default_factory=list)


class ArtifactItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    kind: str
    title: str
    description: str = ""
    parent_id: str | None = None
    rationale: str = ""
    citations: list[Citation] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class SectionContent(BaseModel):
    kind: SectionKind
    blocks: list[TextBlock] = Field(default_factory=list)  # rich_text
    items: list[ArtifactItem] = Field(default_factory=list)  # items

    def is_empty(self) -> bool:
        return not self.blocks and not self.items


class SectionDefinition(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str
    kind: SectionKind
    item_kind: str | None = None
    description: str = ""

    @field_validator("item_kind")
    @classmethod
    def _item_kind_for_items(cls, value: str | None, info: Any) -> str | None:
        if info.data.get("kind") == SectionKind.items and not value:
            raise ValueError("items sections need an item_kind")
        return value


class ArtifactType(BaseModel):
    type: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    description: str = ""
    icon: str = "file-text"
    sections: list[SectionDefinition]

    def section(self, key: str) -> SectionDefinition | None:
        return next((s for s in self.sections if s.key == key), None)

    @property
    def section_keys(self) -> list[str]:
        return [s.key for s in self.sections]


class ArtifactContent(BaseModel):
    """Full content of one Artifact version."""

    type: str
    title: str
    sections: dict[str, SectionContent] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def all_items(self) -> list[tuple[str, ArtifactItem]]:
        return [(key, item) for key, section in self.sections.items() for item in section.items]

    def find_item(self, item_id: str) -> tuple[str, ArtifactItem] | None:
        return next(((k, i) for k, i in self.all_items() if i.id == item_id), None)

    def citations(self) -> list[Citation]:
        result: list[Citation] = []
        for section in self.sections.values():
            for block in section.blocks:
                result += block.citations
            for item in section.items:
                result += item.citations
        return result


class ArtifactReference(BaseModel):
    artifact_id: str
    type: str
    title: str
    version: int
    changed_sections: list[str] = Field(default_factory=list)
    created: bool = False


def empty_content(artifact_type: ArtifactType, title: str) -> ArtifactContent:
    return ArtifactContent(
        type=artifact_type.type,
        title=title,
        sections={s.key: SectionContent(kind=s.kind) for s in artifact_type.sections},
    )


def apply_section_updates(
    content: ArtifactContent, updates: dict[str, SectionContent], artifact_type: ArtifactType
) -> tuple[ArtifactContent, list[str]]:
    """Return a new content where only ``updates`` keys changed, and the list of changed keys.

    Unknown section keys and kind mismatches are rejected (the model cannot invent sections).
    """
    new_sections = dict(content.sections)
    changed: list[str] = []
    for key, section in updates.items():
        definition = artifact_type.section(key)
        if definition is None:
            raise ValueError(f"Unknown section '{key}' for artifact type '{artifact_type.type}'")
        if section.kind != definition.kind:
            raise ValueError(f"Section '{key}' must be {definition.kind}, got {section.kind}")
        if definition.kind == SectionKind.items:
            for item in section.items:
                item.kind = definition.item_kind or item.kind
        if new_sections.get(key) != section:
            new_sections[key] = section
            changed.append(key)
    return content.model_copy(update={"sections": new_sections}), changed


def changed_section_keys(old: ArtifactContent, new: ArtifactContent) -> list[str]:
    keys = list(dict.fromkeys([*old.sections.keys(), *new.sections.keys()]))
    return [k for k in keys if old.sections.get(k) != new.sections.get(k)]


class SectionDiff(BaseModel):
    key: str
    status: Literal["added", "removed", "changed", "unchanged"]
    added_items: list[str] = Field(default_factory=list)
    removed_items: list[str] = Field(default_factory=list)
    changed_items: list[str] = Field(default_factory=list)
    before_text: str = ""
    after_text: str = ""


def section_plain_text(section: SectionContent | None) -> str:
    if section is None:
        return ""
    if section.kind == SectionKind.rich_text:
        return "\n".join(b.text for b in section.blocks)
    return "\n".join(f"- {i.title}: {i.description}".rstrip(": ") for i in section.items)


def compare_contents(old: ArtifactContent, new: ArtifactContent) -> list[SectionDiff]:
    diffs: list[SectionDiff] = []
    keys = list(dict.fromkeys([*old.sections.keys(), *new.sections.keys()]))
    for key in keys:
        before, after = old.sections.get(key), new.sections.get(key)
        if before == after:
            diffs.append(SectionDiff(key=key, status="unchanged"))
            continue
        status: Literal["added", "removed", "changed"]
        status = "added" if before is None or before.is_empty() else "removed" if after is None else "changed"
        diff = SectionDiff(key=key, status=status, before_text=section_plain_text(before), after_text=section_plain_text(after))
        old_items = {i.id: i for i in (before.items if before else [])}
        new_items = {i.id: i for i in (after.items if after else [])}
        diff.added_items = [i for i in new_items if i not in old_items]
        diff.removed_items = [i for i in old_items if i not in new_items]
        diff.changed_items = [i for i in new_items if i in old_items and old_items[i] != new_items[i]]
        diffs.append(diff)
    return diffs
