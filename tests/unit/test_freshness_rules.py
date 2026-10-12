"""Living Artifacts rules: stale, fresh or unverified — never fresh by default."""

from __future__ import annotations

from datetime import UTC, datetime

from nova.domain.freshness import CitedSource, SourceChange, assess, update_instruction

WRITTEN = datetime(2026, 9, 20, tzinfo=UTC)
SOURCE = CitedSource(frozenset({"doc-1", "chunk-1"}), "Q4 Objectives", "forge", frozenset({"goals", "scope"}))


def _change(target: str | None, *, type_: str = "document.new_version", slug: str = "forge", day: int = 25) -> SourceChange:
    return SourceChange(
        f"c-{target}-{day}", slug, type_, "New version", "Q4 Objectives v3", target, datetime(2026, 9, day, tzinfo=UTC)
    )


def test_a_change_to_a_cited_source_after_the_version_makes_the_artifact_stale_and_names_the_sections():
    result = assess([SOURCE], [_change("doc-1")], WRITTEN)
    assert result["status"] == "stale" and result["stale_sections"] == ["goals", "scope"]
    assert result["impacts"][0]["source_title"] == "Q4 Objectives" and result["impacts"][0]["type"] == "document.new_version"


def test_changes_that_do_not_touch_a_cited_source_leave_it_fresh():
    changes = [
        _change("doc-9"),  # another document
        _change("doc-1", day=10),  # older than the version
        _change("doc-1", slug="other"),  # another project
        _change("doc-1", type_="memory.created"),  # a kind of change that does not invalidate a citation
        _change(None),
    ]
    assert assess([SOURCE], changes, WRITTEN)["status"] == "fresh"


def test_nothing_to_check_against_is_unverified_not_fresh():
    assert assess([], [_change("doc-1")], WRITTEN) == {
        "status": "unverified",
        "reason": "no_citations",
        "impacts": [],
        "stale_sections": [],
    }
    unreachable = assess([SOURCE], [], WRITTEN, checked=False)
    assert unreachable["status"] == "unverified" and unreachable["reason"] == "context_unavailable"


def test_the_update_instruction_lists_each_change_once():
    impacts = assess([SOURCE], [_change("doc-1", day=25), _change("chunk-1", day=26)], WRITTEN)["impacts"]
    text = update_instruction(impacts)
    assert text.count("Q4 Objectives v3") == 1 and text.startswith("Some sources this section cites have changed")
