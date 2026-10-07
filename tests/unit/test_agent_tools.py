import json

import pytest

from server.graph.queries import GraphQueryError
from server.pipelines.agent.evidence_log import EvidenceLog
from server.pipelines.agent.tools import execute_tool
from server.pipelines.agent.tools import find_entity as fe_mod
from server.pipelines.agent.tools import get_evidence as ge_mod
from server.pipelines.agent.tools import graph_query as gq_mod
from server.pipelines.agent.tools import neighbors as nb_mod
from server.pipelines.agent.tools import search_text as st_mod
from server.pipelines.agent.tools.base import ToolContext
from server.pipelines.graphrag import expand as expand_mod
from tests.unit.graphrag_fixtures import director, raw_result, txn_edges

NAMES = {
    "C:TATASTEEL": ("Tata Steel Limited", "company"),
    "C:TATAMOTORS": ("Tata Motors Limited", "company"),
    "P:1": ("Anil Kumar Sharma", "person"),
}


@pytest.fixture
def ctx(tracer):  # type: ignore[no-untyped-def]
    return ToolContext("Which directors sit on both boards?", EvidenceLog(), tracer)


@pytest.fixture(autouse=True)
def graph_seams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(expand_mod, "hub_ids", lambda *a, **k: set())
    monkeypatch.setattr(
        nb_mod, "entity_names", lambda ids: {i: NAMES[i] for i in ids if i in NAMES}
    )
    monkeypatch.setattr(
        gq_mod, "entity_names", lambda ids: {i: NAMES[i] for i in ids if i in NAMES}
    )


class Runner:
    def __init__(self, *responses: object) -> None:
        self.responses, self.calls = list(responses), []

    def __call__(self, name: str, params: dict, timeout_s: int | None = None) -> object:
        self.calls.append((name, params, timeout_s))
        out = self.responses.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


# --- find_entity -----------------------------------------------------------


def test_find_entity_lists_candidates_without_logging_evidence(ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        fe_mod,
        "find_candidates",
        lambda name, kind, limit: [
            {
                "entity_id": "C:TATASTEEL",
                "canonical_name": "Tata Steel Limited",
                "kind": "company",
                "match": 100,
            }
        ],
    )
    result = execute_tool(ctx, "find_entity", {"name": "Tata Steel", "kind": "company"})
    assert result.ok and "C:TATASTEEL - Tata Steel Limited (company), match 100" in result.text
    assert len(ctx.log) == 0  # lookups are not facts


def test_find_entity_passes_any_as_no_filter_and_reports_no_match(ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    seen: list = []
    monkeypatch.setattr(fe_mod, "find_candidates", lambda n, k, limit: seen.append(k) or [])
    result = execute_tool(ctx, "find_entity", {"name": "Nope Corp"})
    assert seen == [None]
    assert not result.ok and "no entity matches" in result.text


# --- neighbors ---------------------------------------------------------------


def _steel_board() -> list[dict]:
    return raw_result(
        [
            director("P:1", "C:TATASTEEL", "FY2023-24", "d1", doc_id="a" * 24, page=46,
                     quote="Anil Kumar Sharma | Independent Director"),
        ]
    )  # fmt: skip


def test_neighbors_logs_each_fact_with_its_label_and_source(ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runner = Runner(_steel_board(), raw_result([]))
    monkeypatch.setattr(expand_mod, "run_installed_strict", runner)
    result = execute_tool(
        ctx, "neighbors", {"entity_id": "C:TATASTEEL", "rel_types": ["director_of"]}
    )

    assert result.ok and result.labels == ["E1"]
    assert (
        "[E1] Person: Anil Kumar Sharma" in result.text
        and "Company: Tata Steel Limited" in result.text
    )
    assert "p.46" in result.text and "FY2023-24" in result.text
    assert ctx.log.provenance["d1"]["page_start"] == 46
    assert runner.calls[0][1]["edge_types"] == ["DIRECTOR_OF"]  # lower-case input was normalised


def test_neighbors_hops_and_year_reach_the_expansion(ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runner = Runner(
        _steel_board(), raw_result([director("P:1", "C:TATAMOTORS", "FY2023-24", "d2")])
    )
    monkeypatch.setattr(expand_mod, "run_installed_strict", runner)
    result = execute_tool(
        ctx, "neighbors", {"entity_id": "C:TATASTEEL", "hops": 2, "fiscal_year": "FY2023-24"}
    )
    assert len(runner.calls) == 2  # hop 1 and hop 2
    assert result.ok and len(result.labels) == 2


def test_neighbors_limit_caps_the_facts(ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    many = raw_result([director(f"P:{i}", "C:TATASTEEL", "FY2023-24", f"d{i}") for i in range(30)])
    monkeypatch.setattr(expand_mod, "run_installed_strict", Runner(many, raw_result([])))
    result = execute_tool(ctx, "neighbors", {"entity_id": "C:TATASTEEL", "limit": 5})
    assert len(result.labels) == 5 and "of 30 found" in result.text


def test_neighbors_rejects_a_name_that_is_not_an_id(ctx) -> None:  # type: ignore[no-untyped-def]
    result = execute_tool(ctx, "neighbors", {"entity_id": "Tata Steel"})
    assert not result.ok and "find_entity" in result.text


def test_neighbors_reports_when_nothing_is_found_without_failing(ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(expand_mod, "run_installed_strict", Runner(raw_result([])))
    result = execute_tool(
        ctx, "neighbors", {"entity_id": "C:TATASTEEL", "fiscal_year": "FY2021-22"}
    )
    assert result.ok and "no facts found" in result.text and "FY2021-22" in result.text
    assert len(ctx.log) == 0


def test_neighbors_graph_failure_becomes_an_error_result(ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        expand_mod, "run_installed_strict", Runner(GraphQueryError("down"), GraphQueryError("down"))
    )
    result = execute_tool(ctx, "neighbors", {"entity_id": "C:TATASTEEL"})
    assert not result.ok and "search_text" in result.text


def test_neighbors_shows_a_transaction_with_both_parties(ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    raw = raw_result(
        txn_edges("T1", "C:TATASTEEL", "C:TATAMOTORS", "t1"),
        {"T1": {"nature": "Sale of goods", "amount_inr": 482000000.0, "fiscal_year": "FY2022-23"}},
    )
    monkeypatch.setattr(expand_mod, "run_installed_strict", Runner(raw, raw_result([])))
    result = execute_tool(ctx, "neighbors", {"entity_id": "C:TATASTEEL", "rel_types": ["PARTY_TO"]})
    assert "Tata Steel Limited" in result.text and "Tata Motors Limited" in result.text
    assert "₹ 48.20 crore" in result.text and result.labels == ["E1"]


# --- search_text -------------------------------------------------------------

CHUNK = {
    "chunk_id": "abc123abc123-4", "doc_id": "abc123abc123" + "0" * 12,
    "text": "The auditor is X. " * 5,
    "page_start": 87, "page_end": 88, "section": "auditor", "fiscal_year": "FY2023-24",
}  # fmt: skip


@pytest.fixture
def vector(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    def fake(query: str, k: int, filters: dict | None = None) -> list[dict]:
        calls.append({"query": query, "k": k, "filters": filters})
        return [
            CHUNK,
            {**CHUNK, "chunk_id": "x-1", "section": "governance"},
            {**CHUNK, "chunk_id": "x-2", "doc_id": "bad"},
        ]

    monkeypatch.setattr(st_mod, "vector_search", fake)
    monkeypatch.setattr(st_mod, "_excluded_doc_ids", lambda: {"bad"})
    monkeypatch.setattr(st_mod.RETRIEVAL, "use_reranker", False)
    return calls


def test_search_text_logs_chunks_with_page_ranges(ctx, vector) -> None:  # type: ignore[no-untyped-def]
    result = execute_tool(
        ctx,
        "search_text",
        {"query": "auditor", "company_id": "TATASTEEL", "fiscal_year": "FY2023-24"},
    )
    assert result.ok and result.labels == ["E1", "E2"]  # the excluded document is dropped
    assert "pages 87-88" in result.text and "FY2023-24" in result.text
    assert ctx.log.provenance["abc123abc123-4"]["page_end"] == 88
    assert vector[0]["filters"] == {"company_id": "TATASTEEL", "fiscal_year": "FY2023-24"}


def test_search_text_section_filter_and_k(ctx, vector) -> None:  # type: ignore[no-untyped-def]
    result = execute_tool(ctx, "search_text", {"query": "auditor", "section": "auditor", "k": 1})
    assert result.labels == ["E1"] and "governance" not in result.text


def test_search_text_shows_a_preview_but_logs_the_full_chunk(ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    long = {**CHUNK, "text": "word " * 1000}
    monkeypatch.setattr(st_mod, "vector_search", lambda q, k, filters=None: [long])
    monkeypatch.setattr(st_mod, "_excluded_doc_ids", lambda: set())
    monkeypatch.setattr(st_mod.RETRIEVAL, "use_reranker", False)
    result = execute_tool(ctx, "search_text", {"query": "q"})
    assert len(result.text) < len(long["text"])
    assert ctx.log.items[0].text == long["text"]


def test_search_text_with_no_hits_is_an_error_result(ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(st_mod, "vector_search", lambda q, k, filters=None: [])
    monkeypatch.setattr(st_mod, "_excluded_doc_ids", lambda: set())
    result = execute_tool(ctx, "search_text", {"query": "q"})
    assert not result.ok and "no matching text" in result.text


# --- calculate ---------------------------------------------------------------


def test_calculate_logs_the_computation_as_evidence(ctx) -> None:  # type: ignore[no-untyped-def]
    result = execute_tool(ctx, "calculate", {"expression": "48.2 + 12.5 * 2"})
    assert result.ok and result.text == "[E1] 48.2 + 12.5 * 2 = 73.2"
    assert ctx.log.items[0].kind == "tool_result"
    assert ctx.log.items[0].text == "calculate(48.2 + 12.5 * 2) = 73.2"


@pytest.mark.parametrize(
    ("expr", "fragment"),
    [("1/0", "division by zero"), ("__import__('os')", "not allowed"), ("a + 1", "not allowed"),
     ("9**9999", "exponent"), ("1 +", "cannot evaluate")],
)  # fmt: skip
def test_calculate_errors_are_returned_not_raised(ctx, expr: str, fragment: str) -> None:  # type: ignore[no-untyped-def]
    result = execute_tool(ctx, "calculate", {"expression": expr})
    assert not result.ok and fragment in result.text
    assert len(ctx.log) == 0


# --- graph_query -------------------------------------------------------------


def _gq(ctx, name, params):  # type: ignore[no-untyped-def]
    return execute_tool(
        ctx, "graph_query", {"query_name": name, "params": params, "purpose": "test"}
    )


@pytest.mark.parametrize(
    ("name", "params"),
    [("run_gsql", {"q": "DELETE"}), ("shared_directors; DROP ALL", {}),
     ("path_between", {"source_id": 'C:1" ; DELETE', "target_id": "C:2"}),
     ("shared_directors", {})],
)  # fmt: skip
def test_rejected_calls_never_reach_the_graph(ctx, monkeypatch, name, params) -> None:  # type: ignore[no-untyped-def]
    runner = Runner()
    monkeypatch.setattr(gq_mod, "run_installed_strict", runner)
    result = _gq(ctx, name, params)
    assert not result.ok and "query rejected" in result.text
    assert runner.calls == []


def test_a_valid_query_runs_with_typed_params_and_is_logged(ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    raw = [
        {
            "Shared": [
                {"v_id": "P:1", "v_type": "Person", "attributes": {"name": "Anil Kumar Sharma"}}
            ]
        }
    ]
    runner = Runner(raw)
    monkeypatch.setattr(gq_mod, "run_installed_strict", runner)
    result = _gq(ctx, "shared_directors", {"company_ids": ["C:TATASTEEL", "C:TATAMOTORS"]})

    assert result.ok and result.labels == ["E1"]
    assert "Shared: P:1 [Person] Anil Kumar Sharma" in result.text
    assert "[computed by query]" in result.text and "P:1 = Anil Kumar Sharma" in result.text
    name, params, timeout = runner.calls[0]
    assert name == "shared_directors" and params["companies"] == ["C:TATASTEEL", "C:TATAMOTORS"]
    assert timeout == ctx.cfg.gsql_timeout_seconds
    assert ctx.log.items[0].kind == "tool_result"


def test_untyped_vertex_params_are_sent_with_types(ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runner = Runner([{"@path": ["x"]}])
    monkeypatch.setattr(gq_mod, "run_installed_strict", runner)
    _gq(ctx, "path_between", {"source_id": "P:1", "target_id": "C:TATASTEEL"})
    assert runner.calls[0][1]["source"] == ("P:1", "Person")
    assert runner.calls[0][1]["target"] == ("C:TATASTEEL", "Company")


def test_large_results_are_truncated_with_a_note(ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    raw = [{"Rows": [f"row-{i}" for i in range(500)]}]
    monkeypatch.setattr(gq_mod, "run_installed_strict", Runner(raw))
    result = _gq(ctx, "entity_neighbors", {"entity_ids": ["C:TATASTEEL"]})
    shown = result.text.count("Rows: ")
    assert shown == ctx.cfg.shown_rows
    assert f"{ctx.cfg.gsql_max_rows - ctx.cfg.shown_rows} more rows truncated" in result.text


def test_empty_results_are_explicit(ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(gq_mod, "run_installed_strict", Runner([{"Shared": []}]))
    result = _gq(ctx, "shared_directors", {"company_ids": ["C:TATASTEEL"]})
    assert result.ok and "returned no rows" in result.text and len(ctx.log) == 0


def test_a_failing_query_is_an_error_result(ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(gq_mod, "run_installed_strict", Runner(GraphQueryError("timeout")))
    result = _gq(ctx, "stake_aggregate", {"company_id": "C:TATASTEEL"})
    assert not result.ok and "query failed" in result.text


def test_an_id_without_a_type_prefix_is_rejected_with_advice(ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(gq_mod, "run_installed_strict", Runner())
    result = _gq(ctx, "path_between", {"source_id": "Automobiles", "target_id": "C:1"})
    assert not result.ok and "find_entity" in result.text


# --- get_evidence ------------------------------------------------------------


def test_get_evidence_returns_a_logged_fact(ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    ctx.log.add("triple", "d1", "Person: A -> Company: B\n  source: doc abc, p.46", "a" * 24, 46)
    result = execute_tool(ctx, "get_evidence", {"ref_id": "d1"})
    assert result.ok and result.labels == ["E1"] and "p.46" in result.text


def test_get_evidence_finds_a_transaction_by_either_edge_id(ctx) -> None:  # type: ignore[no-untyped-def]
    ctx.log.add("triple", "t1-r,t1-c", "txn text", "d", 3)
    assert execute_tool(ctx, "get_evidence", {"ref_id": "t1-r,t1-c"}).ok
    assert execute_tool(ctx, "get_evidence", {"ref_id": "t1-c"}).labels == ["E1"]


def test_get_evidence_loads_and_logs_an_unseen_chunk(ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(ge_mod, "load_chunks", lambda d: [CHUNK])
    result = execute_tool(ctx, "get_evidence", {"ref_id": CHUNK["chunk_id"]})
    assert result.ok and result.labels == ["E1"] and "The auditor is X" in result.text
    assert ctx.log.provenance[CHUNK["chunk_id"]]["page_start"] == 87


def test_get_evidence_fetches_an_unseen_edge_from_the_graph(ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    edge = director("P:1", "C:TATASTEEL", "FY2023-24", "deadbeef", page=46)
    runner = Runner([{"@@edges": [edge]}])
    monkeypatch.setattr(ge_mod, "run_installed_strict", runner)
    monkeypatch.setattr(
        nb_mod, "entity_names", lambda ids: {i: NAMES[i] for i in ids if i in NAMES}
    )
    result = execute_tool(ctx, "get_evidence", {"ref_id": "deadbeef"})
    assert (
        result.ok
        and "Anil Kumar Sharma" in result.text
        and runner.calls[0][1] == {"edge_id": "deadbeef"}
    )


def test_get_evidence_unknown_ids_are_errors(ctx, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(ge_mod, "load_chunks", lambda d: [])
    monkeypatch.setattr(ge_mod, "run_installed_strict", Runner([{"@@edges": []}]))
    assert "unknown ref_id" in execute_tool(ctx, "get_evidence", {"ref_id": "nope-1"}).text
    assert "unknown ref_id" in execute_tool(ctx, "get_evidence", {"ref_id": "nope"}).text


def test_every_result_is_json_safe_text(ctx) -> None:  # type: ignore[no-untyped-def]
    result = execute_tool(ctx, "calculate", {"expression": "1+1"})
    json.dumps(result.model_dump())
