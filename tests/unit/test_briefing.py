"""The spoken morning briefing: fixed sentences, nothing classified read aloud."""

from __future__ import annotations

from nova.domain.briefing import BriefItem, script, speakable


def test_a_quiet_day_says_so_and_nothing_else():
    sentences, withheld = script("Yassine", "fr", actions_required=0, running=0, results_ready=0, items=[])
    assert sentences == ["Bonjour Yassine.", "Rien ne demande votre attention pour le moment."] and withheld == 0


def test_the_briefing_counts_then_reads_the_top_items_in_order():
    items = [BriefItem("Approuver le plan de la mission"), BriefItem("PRD périmé"), BriefItem("Relire la story 12")]
    sentences, withheld = script("Yassine", "en", actions_required=3, running=1, results_ready=2, items=items)
    assert sentences[:4] == ["Hello Yassine.", "3 items need you.", "NOVA is working on one task.", "2 results are ready."]
    assert sentences[4:7] == ["First: Approuver le plan de la mission.", "Then: PRD périmé.", "Then: Relire la story 12."]
    assert sentences[-1] == "Everything is in your Inbox." and withheld == 0


def test_only_the_three_top_items_are_read():
    items = [BriefItem(f"Élément {i}") for i in range(6)]
    sentences, _ = script("A", "en", actions_required=6, running=0, results_ready=0, items=items)
    assert sum(1 for s in sentences if s.startswith(("First:", "Then:"))) == 3


def test_classified_items_are_never_spelled_out():
    items = [BriefItem("Budget confidentiel 900 k€", classification=3), BriefItem("Roadmap interne", classification=1)]
    sentences, withheld = script("A", "fr", actions_required=2, running=0, results_ready=0, items=items)
    assert withheld == 1
    assert not any("900" in s or "Budget" in s for s in sentences)
    assert "D’abord : un élément classifié, à consulter à l’écran." in sentences and "Ensuite : Roadmap interne." in sentences


def test_titles_are_read_without_links_markup_or_excess_length():
    assert speakable("**PRD** : voir https://exemple.com/x `ok`") == "PRD : voir ok"
    assert speakable("") == "" and len(speakable("mot " * 100)) <= 110
    sentences, _ = script("A", "en", actions_required=1, running=0, results_ready=0, items=[BriefItem("https://only.link")])
    assert not any(s.startswith("First:") for s in sentences)  # nothing speakable: skipped, not read as an empty line


def test_singular_and_plural_forms():
    one, _ = script("A", "fr", actions_required=1, running=1, results_ready=1, items=[])
    assert one[1:4] == ["Un élément a besoin de vous.", "NOVA travaille sur une tâche.", "Un résultat est prêt."]
