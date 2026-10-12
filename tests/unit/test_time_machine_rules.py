"""Time Machine rules: pairing the Artifacts of two runs and expressing a change."""

from __future__ import annotations

from nova.domain.time_machine import pair_by_type, relative_change, word_count


def test_relative_change_is_withheld_when_there_is_nothing_to_compare_against():
    assert relative_change(1000, 700) == -0.3
    assert relative_change(100, 150) == 0.5
    assert relative_change(0, 10) is None and relative_change(None, 10) is None and relative_change(10, None) is None


def test_artifacts_are_paired_by_type_in_order_and_leftovers_are_kept():
    pairs = pair_by_type([("prd", "a1"), ("backlog", "a2"), ("prd", "a3")], [("prd", "b1"), ("roadmap", "b2")])
    assert pairs == [("prd", "a1", "b1"), ("backlog", "a2", None), ("prd", "a3", None), ("roadmap", None, "b2")]


def test_word_count():
    assert word_count("  two   words\nand more ") == 4 and word_count("") == 0
