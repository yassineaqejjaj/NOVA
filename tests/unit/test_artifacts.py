"""Artifact model: schemas, normalization, versioning helpers, rendering."""

from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator

from nova.artifacts.registry import NormalizationReport, get_artifact_registry
from nova.artifacts.render import render_markdown
from nova.domain.artifacts import (
    ArtifactItem,
    Citation,
    SectionContent,
    apply_section_updates,
    compare_contents,
    empty_content,
)
from nova.domain.enums import SectionKind

registry = get_artifact_registry()
prd = registry.get("prd")
CITES = {"S1": Citation(label="S1", ref="ref-1", title="Vision")}


def test_prd_has_the_23_required_sections():
    titles = [s.title for s in prd.sections]
    assert len(titles) == 23
    for required in (
        "Summary",
        "Problem",
        "Jobs To Be Done",
        "Non-objectives",
        "Out of scope",
        "Acceptance criteria",
        "Decisions",
    ):
        assert required in titles


def test_output_schema_is_valid_json_schema_and_constrains_sections():
    schema = registry.output_schema(prd, ["summary", "functional_requirements"])
    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["sections"]["required"] == ["summary", "functional_requirements"]
    assert schema["properties"]["sections"]["additionalProperties"] is False
    # When tools may be requested, sections are optional: the model asks for tools without writing the step twice.
    with_tools = registry.output_schema(prd, ["summary", "functional_requirements"], with_tools=True)
    Draft202012Validator.check_schema(with_tools)
    assert with_tools["properties"]["sections"]["required"] == [] and "tool_requests" in with_tools["properties"]


def test_normalization_drops_unserved_citations_and_invalid_attributes():
    report = NormalizationReport()
    raw = {
        "functional_requirements": {"items": [
            {"id": "Req Export 1", "title": "Export", "citations": ["S1", "S9"],
             "attributes": {"type": "functional", "priority": "urgent", "unknown": 1}},
        ]},
        "invented_section": {"blocks": []},
    }  # fmt: skip
    sections = registry.normalize_sections(
        prd, raw, allowed_keys=["functional_requirements"], citation_index=CITES, report=report
    )
    item = sections["functional_requirements"].items[0]
    assert item.id == "req-export-1"
    assert [c.label for c in item.citations] == ["S1"] and item.citations[0].ref == "ref-1"
    assert item.attributes == {"type": "functional"}  # "urgent" is not a MoSCoW value; "unknown" is not in the schema
    assert report.dropped_citations == ["S9"] and report.unknown_sections == ["invented_section"]


def test_normalization_keeps_existing_ids_and_resolves_parents():
    content = empty_content(registry.get("backlog"), "Backlog")
    content.sections["epics"] = SectionContent(kind=SectionKind.items, items=[ArtifactItem(id="epic-a", kind="epic", title="A")])
    raw = {"stories": {"items": [
        {"id": "story-1", "title": "S1", "parent_id": "epic-a", "attributes": {"as_a": "user", "i_want": "x"}},
        {"id": "story-2", "title": "S2", "parent_id": "ghost", "attributes": {"as_a": "user", "i_want": "y"}},
        {"id": "story-1", "title": "duplicate id", "attributes": {"as_a": "user", "i_want": "z"}},
    ]}}  # fmt: skip
    scope: set[str] = set()
    sections = registry.normalize_sections(
        registry.get("backlog"), raw, allowed_keys=["stories"], citation_index={}, existing=content, id_scope=scope
    )
    stories = sections["stories"].items
    assert [s.id for s in stories] == ["story-1", "story-2", "story-1-2"]
    assert stories[0].parent_id == "epic-a" and stories[1].parent_id is None


def test_section_updates_touch_only_requested_sections():
    content = empty_content(prd, "PRD")
    update = SectionContent(kind=SectionKind.items, items=[ArtifactItem(kind="metric", title="Adoption")])
    new, changed = apply_section_updates(content, {"metrics": update}, prd)
    assert changed == ["metrics"]
    assert all(new.sections[k] == content.sections[k] for k in content.sections if k != "metrics")
    diff = {d.key: d.status for d in compare_contents(content, new)}
    assert diff["metrics"] == "added" and diff["summary"] == "unchanged"


def test_section_updates_reject_unknown_sections_and_kind_mismatch():
    content = empty_content(prd, "PRD")
    with pytest.raises(ValueError):
        apply_section_updates(content, {"nope": SectionContent(kind=SectionKind.rich_text)}, prd)
    with pytest.raises(ValueError):
        apply_section_updates(content, {"metrics": SectionContent(kind=SectionKind.rich_text)}, prd)


def test_markdown_export_renders_hierarchy_stories_and_sources():
    content = empty_content(registry.get("backlog"), "Backlog")
    content.sections["epics"] = SectionContent(kind=SectionKind.items, items=[ArtifactItem(id="e1", kind="epic", title="Epic")])
    content.sections["stories"] = SectionContent(kind=SectionKind.items, items=[ArtifactItem(
        id="s1", kind="story", title="Story", parent_id="e1", citations=[Citation(label="S1")],
        attributes={"as_a": "PM", "i_want": "export", "so_that": "share", "acceptance_criteria": [{"given": "a", "when": "b", "then": "c"}]},
    )])  # fmt: skip
    md = render_markdown(content, registry.get("backlog"), sources=[{"label": "S1", "title": "Vision", "uri": None}])
    assert "As a PM, I want export, so that share." in md and "Given a, when b, then c" in md
    assert "**Story** [S1]" in md and "## Sources" in md


def test_inline_citation_markers_become_validated_citations():
    """Live finding: open-weight models often write "(S9)" in the text instead of the citations field."""
    report = NormalizationReport()
    raw = {"problem": {"blocks": [{"type": "paragraph", "text": "Desks stay booked (S1) and policy [S7] is ignored."}]}}
    sections = registry.normalize_sections(prd, raw, allowed_keys=["problem"], citation_index=CITES, report=report)
    block = sections["problem"].blocks[0]
    assert block.text == "Desks stay booked and policy is ignored."
    assert [c.label for c in block.citations] == ["S1"] and report.dropped_citations == ["S7"]
