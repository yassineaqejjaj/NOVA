"""Context FORGE hands to NOVA keeps its classification (C0-C3); what is not classified is treated as secret (C3)."""

from __future__ import annotations

from types import SimpleNamespace

from nova.agent.nodes.execution import constrained_tools
from nova.agent.tools.registry import get_tool_registry
from nova.integrations.forge import mapper
from nova.integrations.forge.schemas import NovaRunRequest


def request(**context) -> NovaRunRequest:
    return NovaRunRequest.model_validate({"input": {"prompt": "x"}, "context": context})


def levels(**context) -> list[int]:
    return [i.classification for i in mapper.provided_context(request(**context))]


def test_a_classified_document_keeps_its_level_and_metadata():
    (item,) = mapper.provided_context(
        request(
            documents=[
                {
                    "id": "d1",
                    "title": "Plan",
                    "content": "synthetic",
                    "source": "orbit",
                    "classification": 3,
                    "document_id": "doc-9",
                    "version": 4,
                    "citation": "S7",
                }
            ]
        )
    )
    assert item.classification == 3 and item.document_id == "doc-9" and item.version == 4 and item.ref_id == "d1"


def test_levels_are_kept_per_document():
    docs = [{"id": f"d{n}", "content": "synthetic", "classification": n} for n in (0, 1, 2)]
    assert levels(documents=docs) == [0, 1, 2]


def test_a_document_without_classification_is_secret_never_internal():
    assert levels(documents=[{"id": "d1", "content": "synthetic"}]) == [mapper.UNCLASSIFIED_LEVEL] == [3]


def test_an_unreadable_or_out_of_range_classification_is_not_trusted():
    docs = [{"id": "a", "classification": "secret"}, {"id": "b", "classification": 9}, {"id": "c", "classification": True}]
    assert levels(documents=docs) == [3, 3, 3]


def test_the_declared_maximum_raises_lower_levels_but_never_lowers_one():
    docs = [{"id": "a", "classification": 1}, {"id": "b", "classification": 3}]
    assert levels(documents=docs, max_classification=2) == [2, 3]
    assert levels(documents=docs, orbit_context={"max_classification": 3}) == [3, 3]


def test_facts_carry_no_classification_so_they_are_secret_too():
    assert levels(facts=["a fact"]) == [3]
    assert levels(facts=["a fact"], max_classification=3) == [3]


def test_the_orbit_context_text_becomes_a_source_the_run_can_read():
    items = mapper.provided_context(
        request(documents=[{"id": "d1", "classification": 1}], orbit_context="Assembled ORBIT context.", max_classification=2)
    )
    assert [i.citation for i in items] == ["S1", "S2"]
    text = items[-1]
    assert text.excerpt == "Assembled ORBIT context." and text.source_system == "orbit" and text.classification == 2
    assert text.ref_id == mapper.ORBIT_CONTEXT_REF


def test_the_orbit_context_object_form_is_read_for_its_level_and_text():
    items = mapper.provided_context(request(orbit_context={"text": "From ORBIT.", "max_classification": 1}))
    assert [(i.excerpt, i.classification) for i in items] == [("From ORBIT.", 1)]


def test_an_orbit_context_without_a_level_is_secret():
    assert levels(orbit_context="Assembled ORBIT context.") == [3]


def test_a_blank_orbit_context_adds_nothing():
    assert levels(orbit_context="   ") == [] and levels(orbit_context={"max_classification": 3}) == []


def test_a_secret_document_from_forge_withholds_the_tools_that_write_externally():
    d = SimpleNamespace(tools=get_tool_registry())
    declared = ["search_orbit", "propose_orbit_decision", "publish_artifact_to_orbit"]

    def tools_for(**context):
        return constrained_tools(d, SimpleNamespace(context_items=mapper.provided_context(request(**context))), declared)

    assert "propose_orbit_decision" in tools_for(documents=[{"id": "d1", "classification": 2}])
    for context in ({"documents": [{"id": "d1", "classification": 3}]}, {"documents": [{"id": "d1"}]}):  # no level = secret
        tools = tools_for(**context)
        assert "search_orbit" in tools and not {"propose_orbit_decision", "publish_artifact_to_orbit"} & set(tools)
