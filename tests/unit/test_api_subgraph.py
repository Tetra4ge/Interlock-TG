import pytest

from server.api import subgraph as sg
from server.api.subgraph import (
    MAX_EDGE_IDS,
    SubgraphUnavailable,
    build_subgraph,
    fetch_subgraph,
    parse_edge_ids,
)
from server.graph.queries import GraphQueryError
from server.pipelines.graphrag.expand import parse_triples
from tests.unit.graphrag_fixtures import director, raw_edge, raw_result, txn_edges

NAMES = {
    "C:TATASTEEL": ("Tata Steel Limited", "company"),
    "C:TATAMOTORS": ("Tata Motors Limited", "company"),
    "P:1": ("Anil Kumar Sharma", "person"),
}


@pytest.fixture(autouse=True)
def names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sg, "entity_names", lambda ids: {i: NAMES[i] for i in ids if i in NAMES})


def test_ids_are_split_deduplicated_and_validated() -> None:
    assert parse_edge_ids("a, b ,a,,c") == ["a", "b", "c"]
    assert parse_edge_ids("t1-r,t1-c") == ["t1-r", "t1-c"]  # a transaction's two edges


@pytest.mark.parametrize("bad", ["", " , ", 'a"; DROP', "a b", "x" * 65, "ok,<script>", "a/b"])
def test_bad_edge_ids_are_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_edge_ids(bad)


def test_the_number_of_ids_is_capped() -> None:
    assert len(parse_edge_ids(",".join(f"e{i}" for i in range(MAX_EDGE_IDS)))) == MAX_EDGE_IDS
    with pytest.raises(ValueError, match="at most"):
        parse_edge_ids(",".join(f"e{i}" for i in range(MAX_EDGE_IDS + 1)))


def _triples():  # type: ignore[no-untyped-def]
    raw = raw_result(
        [
            director(
                "P:1", "C:TATASTEEL", "FY2023-24", "d1", doc_id="a" * 24, page=46, quote="Sharma"
            ),
            director("P:1", "C:TATAMOTORS", "FY2023-24", "d2", doc_id="b" * 24, page=12),
            *txn_edges("T1", "C:TATASTEEL", "C:TATAMOTORS", "t1"),
        ],
        {"T1": {"nature": "Sale of goods", "amount_inr": 482000000.0, "fiscal_year": "FY2022-23"}},
    )
    return parse_triples(raw, 1)


def test_only_the_requested_edges_are_returned() -> None:
    out = build_subgraph(_triples(), ["d1"])
    assert [e.id for e in out.edges] == ["d1"] and (out.requested, out.found) == (1, 1)
    assert {n.id for n in out.nodes} == {"P:1", "C:TATASTEEL"}  # no node from an unrequested edge


def test_nodes_are_named_and_edges_carry_provenance() -> None:
    out = build_subgraph(_triples(), ["d1", "d2"])
    labels = {n.id: n.label for n in out.nodes}
    assert labels == {
        "P:1": "Anil Kumar Sharma",
        "C:TATASTEEL": "Tata Steel Limited",
        "C:TATAMOTORS": "Tata Motors Limited",
    }
    first = next(e for e in out.edges if e.id == "d1")
    assert (first.type, first.source, first.target) == ("DIRECTOR_OF", "P:1", "C:TATASTEEL")
    assert (first.doc_id, first.page, first.quote, first.fiscal_year) == (
        "a" * 24,
        46,
        "Sharma",
        "FY2023-24",
    )
    assert first.label == "Independent Director"


def test_a_transaction_node_shows_its_nature_and_amount() -> None:
    out = build_subgraph(_triples(), ["t1-r", "t1-c"])
    txn = next(n for n in out.nodes if n.type == "RelatedPartyTxn")
    assert txn.label == "Sale of goods ₹ 48.20 crore"
    assert {e.id for e in out.edges} == {"t1-r", "t1-c"} and len(out.nodes) == 3


def test_asking_for_edges_that_do_not_exist_reports_how_many_were_found() -> None:
    out = build_subgraph(_triples(), ["d1", "missing"])
    assert (out.requested, out.found) == (2, 1)
    empty = build_subgraph(_triples(), ["nope"])
    assert empty.nodes == [] and empty.edges == [] and empty.found == 0


def test_edges_without_provenance_attributes_still_render() -> None:
    triples = parse_triples(
        raw_result([raw_edge("IN_SECTOR", ("C:TATASTEEL", "Company"), ("Metals", "Sector"))]), 1
    )
    out = build_subgraph(triples, [triples[0].edge_id])
    assert (
        out.edges[0].doc_id == "" and out.edges[0].page == 0 and out.edges[0].label == "in sector"
    )


def test_fetch_calls_the_installed_query_with_the_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def runner(name: str, params: dict, timeout: int | None = None) -> object:
        seen.update(name=name, params=params, timeout=timeout)
        return raw_result([director("P:1", "C:TATASTEEL", "FY2023-24", "d1")])

    monkeypatch.setattr(sg, "run_installed_strict", runner)
    out = fetch_subgraph(["d1", "d9"], timeout_s=7)
    assert seen == {"name": "subgraph_by_edges", "params": {"edge_ids": ["d1", "d9"]}, "timeout": 7}
    assert out.found == 1 and out.requested == 2


def test_a_graph_failure_becomes_subgraph_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def runner(name: str, params: dict, timeout: int | None = None) -> object:
        raise GraphQueryError("subgraph_by_edges: 404 Client Error")

    monkeypatch.setattr(sg, "run_installed_strict", runner)
    with pytest.raises(SubgraphUnavailable, match="404"):
        fetch_subgraph(["d1"])
