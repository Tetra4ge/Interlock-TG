import pytest

from server.graph.stats import StatItem
from server.pipelines.graphrag import global_mode as gm
from server.pipelines.graphrag.linking import LinkPlan

PACK = [
    StatItem(topic="IN_SECTOR", text="Sector Automobiles: 2 companies."),
    StatItem(topic="AUDITED_BY", text="Tata Steel changed auditor."),
    StatItem(topic="COVERAGE", text="The dataset has 26 documents."),
    StatItem(topic="DIRECTOR_OF", text="Tata Steel had 10 directors."),
]


def test_coverage_comes_first_then_requested_topics() -> None:
    ranked = gm.rank_stats(PACK, {"AUDITED_BY"})
    assert [i.topic for i in ranked] == ["COVERAGE", "AUDITED_BY", "IN_SECTOR", "DIRECTOR_OF"]


def test_global_evidence_builds_summary_items_without_a_document(
    monkeypatch: pytest.MonkeyPatch, tracer
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(gm, "dataset_stats_pack", lambda: PACK)
    result = gm.global_evidence(
        "Which companies changed their auditor?", LinkPlan(is_global=True), tracer
    )
    assert result is not None
    items, provenance = result
    assert [i.kind for i in items] == ["summary"] * 4
    assert items[0].text == "The dataset has 26 documents."
    assert items[1].text == "Tata Steel changed auditor."  # "auditor" keyword promoted it
    assert provenance[items[0].ref_id]["doc_id"] == ""
    assert tracer.steps[-1].name == "global_stats"


def test_empty_pack_returns_none(monkeypatch: pytest.MonkeyPatch, tracer) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(gm, "dataset_stats_pack", lambda: [])
    assert gm.global_evidence("How many companies?", LinkPlan(is_global=True), tracer) is None


def test_pack_is_trimmed_to_the_evidence_budget(monkeypatch: pytest.MonkeyPatch, tracer) -> None:  # type: ignore[no-untyped-def]
    big = [StatItem(topic="DIRECTOR_OF", text="word " * 300) for _ in range(40)]
    monkeypatch.setattr(gm, "dataset_stats_pack", lambda: big)
    result = gm.global_evidence("Which sector?", LinkPlan(is_global=True), tracer)
    assert result is not None
    assert 0 < len(result[0]) < 40
