"""Artifact type registry, model-output schemas and normalization.

The model fills sections through a constrained JSON Schema; its output is then normalized:
stable item ids, parent links resolved, attributes validated against the item-kind schema, and
citations kept **only** if they match a context item actually served (no fabricated provenance).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from nova.config import get_settings
from nova.domain.artifacts import (
    ArtifactContent,
    ArtifactItem,
    ArtifactType,
    Citation,
    SectionContent,
    TextBlock,
)
from nova.domain.enums import SectionKind

_ID_RE = re.compile(r"[^a-z0-9_-]+")
# "[S2]", "(S2)", "(S1, S3)", "[S1][S4]" written inline by the model
_INLINE_CITATION = re.compile(r"\s*[\[(]\s*(S\d+(?:\s*[,;/]\s*S\d+)*)\s*[\])]")
BLOCK_TYPES = ["paragraph", "heading", "bullet", "numbered", "quote"]


@dataclass
class NormalizationReport:
    dropped_citations: list[str] = field(default_factory=list)
    dropped_attributes: list[str] = field(default_factory=list)
    unknown_sections: list[str] = field(default_factory=list)


class ArtifactRegistry:
    def __init__(self, types_dir: Path, items_dir: Path) -> None:
        self.types: dict[str, ArtifactType] = {}
        self.item_schemas: dict[str, dict[str, Any]] = {}
        for path in sorted(items_dir.glob("*.json")):
            schema = json.loads(path.read_text())
            Draft202012Validator.check_schema(schema)
            self.item_schemas[path.stem] = schema
        for path in sorted(types_dir.glob("*.yaml")):
            artifact_type = ArtifactType.model_validate(yaml.safe_load(path.read_text()))
            if artifact_type.type != path.stem:
                raise ValueError(f"{path.name}: type '{artifact_type.type}' must match the file name")
            for section in artifact_type.sections:
                if section.item_kind and section.item_kind not in self.item_schemas:
                    raise ValueError(f"{path.name}: unknown item kind '{section.item_kind}'")
            self.types[artifact_type.type] = artifact_type

    def get(self, type_key: str) -> ArtifactType:
        try:
            return self.types[type_key]
        except KeyError as exc:
            raise KeyError(f"Unknown artifact type '{type_key}'") from exc

    # --- Schemas sent to the model ---------------------------------------------------------------

    def section_schema(self, artifact_type: ArtifactType, key: str) -> dict[str, Any]:
        definition = artifact_type.section(key)
        if definition is None:
            raise KeyError(key)
        citations = {"type": "array", "items": {"type": "string"}, "description": "Context labels such as S1"}
        if definition.kind == SectionKind.rich_text:
            block = {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": BLOCK_TYPES},
                    "text": {"type": "string"},
                    "citations": citations,
                },
                "required": ["type", "text"],
                "additionalProperties": False,
            }
            return {
                "type": "object",
                "description": f"{definition.title}. {definition.description}".strip(),
                "properties": {"blocks": {"type": "array", "items": block}},
                "required": ["blocks"],
                "additionalProperties": False,
            }
        item_schema = self.item_schemas[definition.item_kind or "note"]
        attributes = {k: v for k, v in item_schema.items() if k in ("type", "properties", "required", "additionalProperties")}
        item = {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Short stable id, e.g. story-3 (keep existing ids)"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "parent_id": {"type": ["string", "null"], "description": definition.description or "Parent item id"},
                "rationale": {"type": "string", "description": "Why this item exists (one sentence)"},
                "citations": citations,
                "attributes": attributes,
            },
            "required": ["id", "title", "attributes"],
            "additionalProperties": False,
        }
        return {
            "type": "object",
            "description": f"{definition.title}: list of {definition.item_kind} items. {definition.description}".strip(),
            "properties": {"items": {"type": "array", "items": item}},
            "required": ["items"],
            "additionalProperties": False,
        }

    def output_schema(self, artifact_type: ArtifactType, keys: list[str], *, with_tools: bool = False) -> dict[str, Any]:
        """JSON Schema of a step output filling ``keys`` (also used for the Skill's output.schema.json)."""
        properties: dict[str, Any] = {
            "summary": {"type": "string", "description": "One sentence describing what was produced"},
            "sections": {
                "type": "object",
                "properties": {key: self.section_schema(artifact_type, key) for key in keys},
                "required": keys,
                "additionalProperties": False,
            },
        }
        required = ["summary", "sections"]
        if with_tools:
            properties["tool_requests"] = {
                "type": "array",
                "maxItems": 3,
                "description": "Tools to call before producing the final sections (leave empty when not needed)",
                "items": {
                    "type": "object",
                    "properties": {"tool": {"type": "string"}, "arguments": {"type": "object"}, "reason": {"type": "string"}},
                    "required": ["tool", "arguments"],
                },
            }
        return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}

    # --- Normalization of model output ----------------------------------------------------------

    def normalize_sections(
        self,
        artifact_type: ArtifactType,
        raw_sections: dict[str, Any],
        *,
        allowed_keys: list[str],
        citation_index: dict[str, Citation],
        existing: ArtifactContent | None = None,
        report: NormalizationReport | None = None,
        id_scope: set[str] | None = None,
    ) -> dict[str, SectionContent]:
        """``id_scope`` collects ids generated for this Artifact across steps (pass the same set)."""
        report = report or NormalizationReport()
        known_ids = {item.id for _, item in existing.all_items()} if existing else set()
        scope = id_scope if id_scope is not None else set()
        result: dict[str, SectionContent] = {}
        pending_parents: list[tuple[ArtifactItem, str]] = []
        for key, raw in (raw_sections or {}).items():
            definition = artifact_type.section(key)
            if definition is None or key not in allowed_keys:
                report.unknown_sections.append(key)
                continue
            raw = raw if isinstance(raw, dict) else {}
            if definition.kind == SectionKind.rich_text:
                blocks = []
                for b in raw.get("blocks") or []:
                    if not isinstance(b, dict) or not str(b.get("text", "")).strip():
                        continue
                    kind = b.get("type") if b.get("type") in BLOCK_TYPES else "paragraph"
                    text, inline = _extract_inline(str(b["text"]))
                    blocks.append(
                        TextBlock(
                            type=kind,
                            text=text,
                            citations=self._citations([*(b.get("citations") or []), *inline], citation_index, report),
                        )
                    )
                result[key] = SectionContent(kind=SectionKind.rich_text, blocks=blocks)
                continue
            items = []
            validator = Draft202012Validator(self.item_schemas[definition.item_kind or "note"])
            for raw_item in raw.get("items") or []:
                if not isinstance(raw_item, dict) or not str(raw_item.get("title", "")).strip():
                    continue
                title, inline_title = _extract_inline(str(raw_item["title"]))
                description, inline_desc = _extract_inline(str(raw_item.get("description") or ""))
                raw_item = {**raw_item, "title": title or str(raw_item["title"]), "description": description,
                            "citations": [*(raw_item.get("citations") or []), *inline_title, *inline_desc]}  # fmt: skip
                item_id = self._unique_id(str(raw_item.get("id") or raw_item["title"]), known_ids, scope)
                item = ArtifactItem(
                    id=item_id,
                    kind=definition.item_kind or "note",
                    title=str(raw_item["title"]).strip(),
                    description=str(raw_item.get("description") or "").strip(),
                    rationale=str(raw_item.get("rationale") or "").strip(),
                    citations=self._citations(raw_item.get("citations"), citation_index, report),
                    attributes=self._attributes(raw_item.get("attributes"), validator, report, item_id),
                )
                if raw_item.get("parent_id"):
                    pending_parents.append((item, str(raw_item["parent_id"])))
                items.append(item)
            result[key] = SectionContent(kind=SectionKind.items, items=items)
        all_ids = known_ids | scope
        for item, parent in pending_parents:
            candidate = _slug(parent)
            item.parent_id = candidate if candidate in all_ids and candidate != item.id else None
        return result

    @staticmethod
    def _unique_id(raw: str, known: set[str], scope: set[str]) -> str:
        """Keep the model's short id when it is valid; existing ids are reused (updates)."""
        base = _slug(raw)[:40] or "item"
        if base in known and base not in scope:
            scope.add(base)
            return base  # same id as an existing item → update of that item
        candidate, n = base, 2
        while candidate in scope:
            candidate = f"{base}-{n}"
            n += 1
        scope.add(candidate)
        return candidate

    @staticmethod
    def _citations(raw: Any, index: dict[str, Citation], report: NormalizationReport) -> list[Citation]:
        result: list[Citation] = []
        for label in raw or []:
            label = str(label).strip().strip("[]")
            if label in index:
                if all(c.label != label for c in result):
                    result.append(index[label])
            else:
                report.dropped_citations.append(label)
        return result

    @staticmethod
    def _attributes(raw: Any, validator: Draft202012Validator, report: NormalizationReport, item_id: str) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        props = validator.schema.get("properties", {})
        clean: dict[str, Any] = {}
        for key, value in raw.items():
            if key not in props or value in (None, ""):
                if key not in props:
                    report.dropped_attributes.append(f"{item_id}.{key}")
                continue
            single = Draft202012Validator({"type": "object", "properties": {key: props[key]}})
            if single.is_valid({key: value}):
                clean[key] = value
            else:
                report.dropped_attributes.append(f"{item_id}.{key}")
        return clean


def _extract_inline(text: str) -> tuple[str, list[str]]:
    """Move inline citation markers into structured citations (validated against the served context later)."""
    labels: list[str] = []

    def collect(match: re.Match[str]) -> str:
        labels.extend(label.strip() for label in re.split(r"[,;/]", match.group(1)))
        return ""

    cleaned = _INLINE_CITATION.sub(collect, text)
    return re.sub(r"\s+([.,;:])", r"\1", cleaned).strip(), labels


def _slug(value: str) -> str:
    return _ID_RE.sub("-", value.strip().lower()).strip("-")


@lru_cache
def get_artifact_registry() -> ArtifactRegistry:
    settings = get_settings()
    return ArtifactRegistry(settings.artifact_types_dir, settings.item_schemas_dir)
