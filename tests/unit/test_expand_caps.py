import pytest

from server.graph.queries import GraphQueryError
from server.pipelines.config import GraphRAGConfig
from server.pipelines.graphrag import expand as expand_mod
from server.pipelines.graphrag.expand import (
    ExpansionFailed,
    cap_per_seed,
    expand,
    filter_fiscal_years,
    frontier_ids,
    incomplete_transactions,
    parse_triples,
    seed_ids,
)
from server.pipelines.graphrag.linking import LinkedEntity
from server.pipelines.graphrag.models import Triple
from server.pipelines.graphrag.relations import RelationChoice
from tests.unit.graphrag_fixtures import director, raw_edge, raw_result, triple, txn_edges

ALL = RelationChoice(types=["DIRECTOR_OF", "PARTY_TO", "AUDITED_BY"], explicit=[])
CFG = GraphRAGConfig(fanout_hop1=3, fanout_hop2=2, max_hops=2)


class Runner:
    """Stands in for run_installed_strict: answers each call from a queue."""

    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, name: str, params: dict, timeout_s: int | None = None) -> object:
        self.calls.append({"name": name, **params, "timeout": timeout_s})
        out = self.responses.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def _patch(monkeypatch: pytest.MonkeyPatch, runner: Runner) -> Runner:
    monkeypatch.setattr(expand_mod, "run_installed_strict", runner)
    return runner


# --- parsing -------------------------------------------------------------


def test_parse_normalises_reverse_edges_and_attaches_the_transaction() -> None:
    raw = raw_result(
        [
            raw_edge(
                "HAS_DIRECTOR", ("C:1", "Company"), ("P:1", "Person"), "e1", fiscal_year="FY2023-24"
            ),
            *txn_edges("T1", "C:1", "C:2", "t1"),
            raw_edge(
                "HAS_PARTY",
                ("T9", "RelatedPartyTxn"),
                ("C:3", "Company"),
                "t9-c",
                side="counterparty",
            ),
            raw_edge("SOMETHING_ELSE", ("C:1", "Company"), ("C:2", "Company"), "x"),
        ],
        {"T1": {"nature": "Sale of goods", "amount_inr": 482000000.0, "fiscal_year": "FY2022-23"}},
    )
    triples = {t.edge_id: t for t in parse_triples(raw, hop=1)}

    assert set(triples) == {"e1", "t1-r", "t1-c", "t9-c"}  # unknown relation dropped
    assert (triples["e1"].rel, triples["e1"].src_id, triples["e1"].dst_id) == (
        "DIRECTOR_OF",
        "P:1",
        "C:1",
    )
    assert triples["t1-r"].txn == {
        "nature": "Sale of goods",
        "amount_inr": 482000000.0,
        "fiscal_year": "FY2022-23",
    }
    assert triples["t1-r"].fiscal_year == "FY2022-23"  # taken from the transaction
    assert (triples["t9-c"].src_id, triples["t9-c"].dst_id) == ("C:3", "T9")


def test_parse_gives_provenance_free_edges_a_stable_id() -> None:
    raw = raw_result([raw_edge("IN_SECTOR", ("C:1", "Company"), ("Auto", "Sector"))])
    a = parse_triples(raw, 1)[0]
    b = parse_triples(raw, 1)[0]
    assert a.edge_id == b.edge_id and len(a.edge_id) == 16


@pytest.mark.parametrize("raw", [None, [], {}, "garbage", [None, 3], [{"edges": "x"}]])
def test_parse_tolerates_unexpected_shapes(raw: object) -> None:
    assert parse_triples(raw, 1) == []


def test_parse_dedupes_by_edge_id() -> None:
    e = director("P:1", "C:1", "FY2023-24", "e1")
    assert len(parse_triples(raw_result([e, e]), 1)) == 1


# --- filtering and caps ---------------------------------------------------


def test_fiscal_year_filter_keeps_matching_and_yearless_edges() -> None:
    ts = [
        triple(edge_id="a", fy="FY2023-24"),
        triple(edge_id="b", fy="FY2021-22"),
        triple("SUBSIDIARY_OF", "C:2", "C:1", edge_id="c", fy=""),
    ]
    assert {t.edge_id for t in filter_fiscal_years(ts, ["FY2023-24"])} == {"a", "c"}
    assert len(filter_fiscal_years(ts, [])) == 3


def test_fanout_is_per_seed_newest_year_first() -> None:
    ts = [
        triple(src=f"P:{i}", dst="C:1", edge_id=f"e{i}", fy=f"FY202{i % 4}-2{i % 4 + 1}")
        for i in range(10)
    ]
    kept = cap_per_seed(ts, {"C:1"}, fanout=3)
    assert len(kept) == 3
    years = sorted((t.fiscal_year for t in ts), reverse=True)[:3]
    assert sorted((t.fiscal_year for t in kept), reverse=True) == years


def test_fanout_is_applied_to_each_seed_separately() -> None:
    ts = [
        triple(src=f"P:{i}", dst=seed, edge_id=f"{seed}-{i}")
        for seed in ("C:1", "C:2")
        for i in range(6)
    ]
    assert len(cap_per_seed(ts, {"C:1", "C:2"}, fanout=2)) == 4


def test_hubs_and_seeds_never_enter_the_frontier() -> None:
    ts = [
        triple("AUDITED_BY", "C:1", "A:hub", edge_id="e1"),
        triple("DIRECTOR_OF", "P:1", "C:1", edge_id="e2"),
        triple("DIRECTOR_OF", "P:2", "C:1", edge_id="e3"),
    ]
    assert frontier_ids(ts, {"C:1"}, {"A:hub"}) == ["P:1", "P:2"]


# --- end-to-end expansion -------------------------------------------------


def test_expand_runs_hop2_from_non_hub_neighbours_and_excludes_hubs(
    monkeypatch: pytest.MonkeyPatch, tracer
) -> None:  # type: ignore[no-untyped-def]
    hop1 = raw_result(
        [
            director("P:1", "C:1", "FY2023-24", "d1"),
            raw_edge(
                "AUDITED_BY",
                ("C:1", "Company"),
                ("A:hub", "AuditFirm"),
                "a1",
                fiscal_year="FY2023-24",
            ),
        ]
    )
    hop2 = raw_result([director("P:1", "C:2", "FY2023-24", "d2")])
    runner = _patch(monkeypatch, Runner(hop1, hop2))

    out = expand(["C:1"], ALL, ["FY2023-24"], tracer, CFG, hubs={"A:hub"})

    assert {t.edge_id: t.hop for t in out} == {"d1": 1, "a1": 1, "d2": 2}
    first, second = runner.calls
    assert first["seed_ids"] == ["C:1"] and first["excluded"] == ["-"]
    assert second["seed_ids"] == ["P:1"]  # the hub audit firm is not expanded
    assert second["excluded"] == ["A:hub"]
    assert "AUDITED_BY" not in second["edge_types"]  # hub relation dropped at hop 2
    assert second["timeout"] == CFG.gsql_timeout_seconds


def test_expand_keeps_hub_relations_at_hop2_when_requested(
    monkeypatch: pytest.MonkeyPatch, tracer
) -> None:  # type: ignore[no-untyped-def]
    asked = RelationChoice(types=["AUDITED_BY", "DIRECTOR_OF"], explicit=["AUDITED_BY"])
    runner = _patch(
        monkeypatch, Runner(raw_result([director("P:1", "C:1", "FY2023-24", "d1")]), raw_result([]))
    )
    expand(["C:1"], asked, [], tracer, CFG, hubs=set())
    assert "AUDITED_BY" in runner.calls[1]["edge_types"]


def test_expand_respects_max_hops_one(monkeypatch: pytest.MonkeyPatch, tracer) -> None:  # type: ignore[no-untyped-def]
    runner = _patch(monkeypatch, Runner(raw_result([director("P:1", "C:1", "FY2023-24", "d1")])))
    expand(["C:1"], ALL, [], tracer, GraphRAGConfig(max_hops=1), hubs=set())
    assert len(runner.calls) == 1


def test_expand_applies_per_seed_fanout_to_every_hop(
    monkeypatch: pytest.MonkeyPatch, tracer
) -> None:  # type: ignore[no-untyped-def]
    hop1 = raw_result([director(f"P:{i}", "C:1", "FY2023-24", f"h1-{i}") for i in range(8)])
    hop2 = raw_result(
        [
            director(f"P:{i}", f"C:{i + 10}", "FY2023-24", f"h2-{i}-{j}")
            for i in range(8)
            for j in range(5)
        ]
    )
    _patch(monkeypatch, Runner(hop1, hop2))

    out = expand(["C:1"], ALL, [], tracer, CFG, hubs=set())

    assert sum(t.hop == 1 for t in out) == CFG.fanout_hop1
    per_person: dict[str, int] = {}
    for t in out:
        if t.hop == 2:
            per_person[t.src_id] = per_person.get(t.src_id, 0) + 1
    assert len(per_person) == CFG.fanout_hop1  # only the capped hop-1 neighbours expand
    assert set(per_person.values()) == {CFG.fanout_hop2}


def test_transaction_completion_keeps_the_counterparty_edge(
    monkeypatch: pytest.MonkeyPatch, tracer
) -> None:  # type: ignore[no-untyped-def]
    raw = raw_result(
        txn_edges("T1", "C:1", "C:2", "t1"),
        {"T1": {"nature": "Sale of goods", "fiscal_year": "FY2022-23"}},
    )
    _patch(monkeypatch, Runner(raw, raw_result([])))
    out = expand(["C:1"], ALL, ["FY2022-23"], tracer, CFG, hubs=set())

    assert {t.edge_id for t in out} == {"t1-r", "t1-c"}
    assert incomplete_transactions(out) == []
    assert "C:2" in frontier_ids(out, {"C:1"}, set())  # the counterparty is a hop-2 seed


def test_incomplete_transactions_are_reported() -> None:
    lone = Triple(
        edge_id="x",
        rel="PARTY_TO",
        src_id="C:1",
        src_type="Company",
        dst_id="T1",
        dst_type="RelatedPartyTxn",
    )
    assert incomplete_transactions([lone]) == ["T1"]


def test_failed_call_is_retried_once_with_a_smaller_fanout(
    monkeypatch: pytest.MonkeyPatch, tracer
) -> None:  # type: ignore[no-untyped-def]
    ok = raw_result([director("P:1", "C:1", "FY2023-24", "d1")])
    runner = _patch(monkeypatch, Runner(GraphQueryError("timeout"), ok, raw_result([])))
    out = expand(["C:1"], ALL, [], tracer, CFG, hubs=set())

    assert [t.edge_id for t in out] == ["d1"]
    assert runner.calls[1]["max_rows"] < runner.calls[0]["max_rows"]
    assert any(s.error and "timeout" in s.error for s in tracer.steps)


def test_two_failures_raise_expansion_failed(monkeypatch: pytest.MonkeyPatch, tracer) -> None:  # type: ignore[no-untyped-def]
    _patch(monkeypatch, Runner(GraphQueryError("timeout"), GraphQueryError("timeout again")))
    with pytest.raises(ExpansionFailed, match="timeout again"):
        expand(["C:1"], ALL, [], tracer, CFG, hubs=set())


def test_empty_subgraph_returns_nothing(monkeypatch: pytest.MonkeyPatch, tracer) -> None:  # type: ignore[no-untyped-def]
    _patch(monkeypatch, Runner(raw_result([])))
    assert expand(["C:1"], ALL, [], tracer, CFG, hubs=set()) == []


def test_no_seeds_makes_no_call(monkeypatch: pytest.MonkeyPatch, tracer) -> None:  # type: ignore[no-untyped-def]
    runner = _patch(monkeypatch, Runner())
    assert expand([], ALL, [], tracer, CFG, hubs=set()) == []
    assert runner.calls == []


def test_sector_links_expand_to_member_companies() -> None:
    linked = [
        LinkedEntity(mention="autos", entity_id="Automobiles", kind="sector", status="linked"),
        LinkedEntity(
            mention="Tata Motors", entity_id="C:TATAMOTORS", kind="company", status="linked"
        ),
    ]
    ids = seed_ids(linked)
    assert "C:TATAMOTORS" in ids and "C:BAJAJ-AUTO" in ids
    assert len(ids) == len(set(ids))
