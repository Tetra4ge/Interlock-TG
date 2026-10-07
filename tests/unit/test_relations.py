import pytest

from server.pipelines.graphrag.linking import RELATION_TYPES, LinkPlan
from server.pipelines.graphrag.relations import choose_relations, keyword_relations


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Which companies have pledged shares?", "HOLDS_STAKE"),
        ("Who is the independent director of Tata Steel?", "DIRECTOR_OF"),
        ("Who audited Tata Motors?", "AUDITED_BY"),
        ("List related party transactions of Tata Motors", "PARTY_TO"),
        ("Which subsidiaries does Tata Steel have?", "SUBSIDIARY_OF"),
        ("Was the firm penalised by a regulator?", "NAMED_IN"),
        ("Which sector is the largest?", "IN_SECTOR"),
    ],
)
def test_keyword_rules(question: str, expected: str) -> None:
    assert expected in keyword_relations(question)


def test_pledged_shares_adds_holds_stake_to_the_models_choice() -> None:
    plan = LinkPlan(relation_types=["DIRECTOR_OF"])
    choice = choose_relations("Who pledged shares of Tata Motors?", plan)
    assert set(choice.types) == {"DIRECTOR_OF", "HOLDS_STAKE"}


def test_empty_result_uses_all_types() -> None:
    choice = choose_relations("Tell me about Tata Steel", LinkPlan())
    assert set(choice.types) == set(RELATION_TYPES)
    assert choice.explicit == []


def test_hub_relations_are_dropped_at_hop2_unless_requested() -> None:
    all_types = choose_relations("Tell me about Tata Steel", LinkPlan())
    assert "AUDITED_BY" not in all_types.hop2_types
    assert "IN_SECTOR" not in all_types.hop2_types
    assert "DIRECTOR_OF" in all_types.hop2_types

    asked = choose_relations("Who audited Tata Steel and its directors?", LinkPlan())
    assert "AUDITED_BY" in asked.hop2_types


def test_choice_is_traced(tracer) -> None:  # type: ignore[no-untyped-def]
    choose_relations("Who audited Tata Steel?", LinkPlan(), tracer)
    assert tracer.steps[-1].name == "choose_relations"
    assert "AUDITED_BY" in tracer.steps[-1].output_summary
