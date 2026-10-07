from server.pipelines.config import GraphRAGConfig
from server.pipelines.graphrag.models import Triple
from server.pipelines.graphrag.rank import rank_and_cap, score_triple
from tests.unit.graphrag_fixtures import raw_edge, triple

NAMES = {
    "C:1": ("Tata Steel Limited", "company"),
    "P:1": ("Anil Kumar Sharma", "person"),
    "C:2": ("Example Trading Private Limited", "company"),
}


def _rank(triples: list[Triple], **kw) -> list[Triple]:  # type: ignore[no-untyped-def]
    args = {
        "linked_ids": {"C:1"},
        "requested": set(),
        "fiscal_years": [],
        "question": "Who are the directors of Tata Steel?",
        "names": NAMES,
        "cfg": GraphRAGConfig(),
    }
    args.update(kw)
    return rank_and_cap(triples, **args)


def test_triples_touching_linked_entities_outrank_others() -> None:
    far = triple(src="P:9", dst="C:9", edge_id="far", hop=2)
    near = triple(src="P:1", dst="C:1", edge_id="near")
    assert [t.edge_id for t in _rank([far, near])] == ["near", "far"]


def test_requested_relation_and_matching_year_raise_the_score() -> None:
    q = "Who audited Tata Steel in FY2023-24?"
    a = score_triple(
        triple("AUDITED_BY", "C:1", "A:1"), {"C:1"}, {"AUDITED_BY"}, ["FY2023-24"], q.lower(), NAMES
    )
    b = score_triple(
        triple("AUDITED_BY", "C:1", "A:1", fy="FY2021-22"),
        {"C:1"},
        set(),
        ["FY2023-24"],
        q.lower(),
        NAMES,
    )
    assert a - b == 2.0 + 1.5


def test_mentioned_endpoint_and_dataset_company_add_to_the_score() -> None:
    base = score_triple(triple(src="P:8", dst="C:8"), set(), set(), [], "tata steel", NAMES)
    mentioned = score_triple(triple(src="P:8", dst="C:1"), set(), set(), [], "tata steel", NAMES)
    in_dataset = score_triple(
        triple(src="P:8", dst="C:TATASTEEL"), set(), set(), [], "tata steel", NAMES
    )
    assert mentioned - base == 1.0
    assert in_dataset - base == 0.5


def test_never_more_than_max_triples() -> None:
    ts = [triple(src=f"P:{i}", dst="C:1", edge_id=f"e{i}") for i in range(40)]
    assert len(_rank(ts, cfg=GraphRAGConfig(max_triples=10))) == 10


def test_duplicate_edge_ids_are_dropped() -> None:
    t = triple(edge_id="same")
    assert len(_rank([t, t.model_copy()])) == 1


def test_each_requested_relation_keeps_a_minimum_share() -> None:
    directors = [triple(src=f"P:{i}", dst="C:1", edge_id=f"d{i}") for i in range(30)]
    auditors = [triple("AUDITED_BY", "C:9", f"A:{i}", edge_id=f"a{i}", hop=2) for i in range(6)]
    out = _rank(
        directors + auditors,
        requested={"DIRECTOR_OF", "AUDITED_BY"},
        cfg=GraphRAGConfig(max_triples=10, min_per_relation=4),
    )
    assert len(out) == 10
    assert sum(t.rel == "AUDITED_BY" for t in out) >= 4


def test_a_transaction_is_never_split_by_the_cap() -> None:
    def party(edge_id: str, who: str, side: str) -> Triple:
        return Triple(
            edge_id=edge_id, rel="PARTY_TO", src_id=who, src_type="Company",
            dst_id="T1", dst_type="RelatedPartyTxn", attrs={"side": side},
        )  # fmt: skip

    txn = [party("t-r", "C:1", "reporting"), party("t-c", "C:2", "counterparty")]
    filler = [triple(src=f"P:{i}", dst="C:1", edge_id=f"e{i}") for i in range(5)]
    for cap in range(1, 8):
        out = _rank(txn + filler, cfg=GraphRAGConfig(max_triples=cap, min_per_relation=0))
        ids = {t.edge_id for t in out}
        assert len(out) <= cap
        assert ("t-r" in ids) == ("t-c" in ids)


def test_ranking_is_deterministic() -> None:
    ts = [triple(src=f"P:{i}", dst="C:1", edge_id=f"e{i}") for i in range(12)]
    first = [t.edge_id for t in _rank(ts, cfg=GraphRAGConfig(max_triples=5))]
    second = [t.edge_id for t in _rank(list(reversed(ts)), cfg=GraphRAGConfig(max_triples=5))]
    assert first == second


def test_provenance_free_edges_still_rank() -> None:
    raw = raw_edge("IN_SECTOR", ("C:1", "Company"), ("Auto", "Sector"))
    t = Triple(
        edge_id="s",
        rel="IN_SECTOR",
        src_id="C:1",
        src_type="Company",
        dst_id="Auto",
        dst_type="Sector",
        attrs=raw["attributes"],
    )
    assert _rank([t])[0].edge_id == "s"
