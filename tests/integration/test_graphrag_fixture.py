"""GraphRAG pipeline against a fixture graph.

No live TigerGraph or LLM is available here, so the GSQL runner, entity index,
vector index and both LLM calls (planning + final answer) are replaced with
fixture data: a small board-interlock graph in which one director sits on two
Tata boards. The pipeline code between those seams is real.
"""

import json

import pytest

from server.graph.queries import GraphQueryError
from server.llm.models import LLMResponse
from server.pipelines import rag as rag_mod
from server.pipelines.common import answer as answer_mod
from server.pipelines.common import tracer as tracer_mod
from server.pipelines.graphrag import expand as expand_mod
from server.pipelines.graphrag import linked_text as lt_mod
from server.pipelines.graphrag import linking as linking_mod
from server.pipelines.graphrag import pipeline as pipe_mod
from server.pipelines.graphrag.pipeline import GraphRAGPipeline
from server.pipelines.models import Status
from tests.unit.graphrag_fixtures import director, raw_result, txn_edges

STEEL_DOC, MOTORS_DOC = "a" * 24, "b" * 24
QUESTION = "Which independent director of Tata Steel also sits on the board of Tata Motors?"

CANDS = {
    "Tata Steel": {
        "entity_id": "C:TATASTEEL",
        "canonical_name": "Tata Steel Limited",
        "kind": "company",
    },
    "Tata Motors": {
        "entity_id": "C:TATAMOTORS",
        "canonical_name": "Tata Motors Limited",
        "kind": "company",
    },
}
NAMES = {
    "C:TATASTEEL": ("Tata Steel Limited", "company"),
    "C:TATAMOTORS": ("Tata Motors Limited", "company"),
    "P:1": ("Anil Kumar Sharma", "person"),
    "P:2": ("Rajesh Verma", "person"),
}

HOP1 = raw_result(
    [
        director("P:1", "C:TATASTEEL", "FY2023-24", "d-steel-1", doc_id=STEEL_DOC, page=46,
                 quote="Anil Kumar Sharma | Independent Director"),
        director("P:2", "C:TATASTEEL", "FY2023-24", "d-steel-2", doc_id=STEEL_DOC, page=46,
                 quote="Rajesh Verma | Independent Director"),
    ]
)  # fmt: skip
HOP2 = raw_result(
    [
        director("P:1", "C:TATAMOTORS", "FY2023-24", "d-motors-1", doc_id=MOTORS_DOC, page=12,
                 quote="Anil Kumar Sharma | Independent Director"),
    ]
)  # fmt: skip
CHUNKS = [
    {
        "Chunks": [
            {
                "v_id": "chunk-g1",
                "v_type": "Chunk",
                "attributes": {
                    "doc_id": STEEL_DOC, "text": "The board of Tata Steel has twelve directors.",
                    "section": "governance", "page_start": 45, "page_end": 46,
                    "fiscal_year": "FY2023-24",
                },
            }
        ]
    }
]  # fmt: skip

PLAN = {
    "mentions": [
        {"text": "Tata Steel", "kind": "company"},
        {"text": "Tata Motors", "kind": "company"},
    ],
    "relation_types": ["DIRECTOR_OF"],
    "fiscal_years": [],
    "is_global": False,
}
ANSWER = {
    "answer_type": "entity",
    "answer_short": "Anil Kumar Sharma",
    "answer_long": "Anil Kumar Sharma sits on both boards [E1].",
    "citations": [{"evidence_id": "E1", "quote": "Anil Kumar Sharma | Independent Director"}],
}
NOT_FOUND = {
    "answer_type": "not_found",
    "answer_short": "not found in the data",
    "answer_long": "The evidence does not say.",
    "citations": [],
}


class FakeConn:
    def execute(self, sql: str, params: list | None = None) -> None:
        return None

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


def _llm(plan: object = PLAN, answer: object = ANSWER, plan_error: str | None = None):  # type: ignore[no-untyped-def]
    calls: list[str] = []

    def call(req):  # type: ignore[no-untyped-def]
        is_plan = "Identify what this question needs" in req.messages[-1].content
        calls.append("plan" if is_plan else "answer")
        if is_plan:
            return LLMResponse(
                content=json.dumps(plan),
                tokens_in=100,
                tokens_out=30,
                cost_usd=0.0,
                error=plan_error,
            )
        return LLMResponse(content=json.dumps(answer), tokens_in=500, tokens_out=60, cost_usd=0.0)

    call.calls = calls  # type: ignore[attr-defined]
    return call


class Graph:
    """Fixture for the three graph seams; `expand_responses` is consumed in order."""

    def __init__(self, *expand_responses: object) -> None:
        self.expand_responses = list(expand_responses)
        self.expand_calls: list[dict] = []

    def run(self, name: str, params: dict, timeout_s: int | None = None) -> object:
        self.expand_calls.append(params)
        out = self.expand_responses.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


@pytest.fixture(autouse=True)
def seams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracer_mod, "connect", lambda: FakeConn())
    monkeypatch.setattr(pipe_mod, "_excluded_doc_ids", lambda: set())
    monkeypatch.setattr(rag_mod, "_excluded_doc_ids", lambda: set())
    monkeypatch.setattr(rag_mod.RETRIEVAL, "use_reranker", False)
    monkeypatch.setattr(lt_mod.RETRIEVAL, "use_reranker", False)
    monkeypatch.setattr(expand_mod, "hub_ids", lambda *a, **k: set())
    monkeypatch.setattr(
        pipe_mod, "entity_names", lambda ids: {i: NAMES[i] for i in ids if i in NAMES}
    )
    monkeypatch.setattr(
        linking_mod,
        "entity_search",
        lambda text, kind=None, limit=5: (
            [dict(CANDS[text], score=90, names=[CANDS[text]["canonical_name"]])]
            if text in CANDS
            else []
        ),
    )
    monkeypatch.setattr(lt_mod, "chunks_for_entities_strict", lambda ids, limit, t=None: CHUNKS)
    monkeypatch.setattr(lt_mod, "score_chunks", lambda q, ids: {i: 0.8 for i in ids})
    monkeypatch.setattr(
        rag_mod,
        "vector_search",
        lambda question, k, filters=None: [
            {
                "chunk_id": "vec-1", "doc_id": STEEL_DOC, "text": "Vector evidence about boards.",
                "page_start": 9, "page_end": 9, "section": "governance", "fiscal_year": "FY2023-24",
            }
        ],
    )  # fmt: skip


def _use(monkeypatch: pytest.MonkeyPatch, graph: Graph, llm=None) -> object:  # type: ignore[no-untyped-def]
    llm = llm or _llm()
    monkeypatch.setattr(expand_mod, "run_installed_strict", graph.run)
    monkeypatch.setattr(linking_mod, "call_llm", llm)
    monkeypatch.setattr(answer_mod, "call_llm", llm)
    return llm


def _names(result) -> list[str]:  # type: ignore[no-untyped-def]
    return [s.name for s in result.trace]


def test_multi_hop_question_is_answered_from_a_two_hop_subgraph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, Graph(HOP1, HOP2))
    result = GraphRAGPipeline().answer(QUESTION, "req-1")

    assert result.pipeline == "graphrag"
    assert result.status == Status.OK
    assert result.answer_short == "Anil Kumar Sharma"

    refs = {e.ref_id: e for e in result.evidence}
    assert {"d-steel-1", "d-steel-2", "d-motors-1"} <= set(refs)  # hop-1 and hop-2 triples
    assert refs["d-motors-1"].kind == "triple"
    assert any(e.kind == "chunk" for e in result.evidence)  # linked text rides along

    # E1 is the best-ranked triple; the citation resolves to its real doc and page.
    assert len(result.citations) == 1
    assert result.citations[0].page in (46, 12)
    assert result.citations[0].doc_id in (STEEL_DOC, MOTORS_DOC)

    assert _names(result) == [
        "link_plan", "link_entities", "choose_relations", "expand_hop(hop 1)",
        "expand_hop(hop 2)", "expand", "linked_text", "budget_split", "final_answer",
        "validate_citations",
    ]  # fmt: skip
    assert result.usage.llm_calls == 2  # planning + answer, both counted


def test_triple_evidence_names_both_boards_with_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, Graph(HOP1, HOP2))
    result = GraphRAGPipeline().answer(QUESTION, "req-2")
    text = "\n".join(e.text for e in result.evidence if e.kind == "triple")
    assert (
        "Anil Kumar Sharma" in text
        and "Tata Steel Limited" in text
        and "Tata Motors Limited" in text
    )
    assert "p.46" in text and "p.12" in text


def test_no_linked_entity_falls_back_to_vector_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = {**PLAN, "mentions": [{"text": "Nonexistent Corp", "kind": "company"}]}
    graph = Graph()
    _use(monkeypatch, graph, _llm(plan=plan))
    result = GraphRAGPipeline().answer("Who audits Nonexistent Corp?", "req-3")

    assert result.status == Status.OK
    assert graph.expand_calls == []  # never touched the graph
    fallback = next(s for s in result.trace if s.name == "fallback")
    assert (
        fallback.input_summary == "no_entity_linked"
        and fallback.output_summary == "fallback=vector"
    )
    assert [e.kind for e in result.evidence] == ["chunk"]
    assert "vector_search" in _names(result)


def test_expansion_failure_falls_back_to_vector_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = Graph(GraphQueryError("timeout"), GraphQueryError("timeout"))
    _use(monkeypatch, graph)
    result = GraphRAGPipeline().answer(QUESTION, "req-4")

    assert result.status == Status.OK
    fallback = next(s for s in result.trace if s.name == "fallback")
    assert fallback.input_summary == "expansion_failed"
    assert "timeout" in (fallback.error or "")
    assert [e.kind for e in result.evidence] == ["chunk"]
    assert len(graph.expand_calls) == 2  # tried once, retried once


def test_empty_subgraph_falls_back_to_vector_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, Graph(raw_result([])))
    result = GraphRAGPipeline().answer(QUESTION, "req-5")
    assert next(s for s in result.trace if s.name == "fallback").input_summary == "empty_subgraph"
    assert [e.kind for e in result.evidence] == ["chunk"]


def test_failed_planning_call_falls_back_to_keyword_planning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, Graph(HOP1, HOP2), _llm(plan_error="rate_limited"))
    result = GraphRAGPipeline().answer(QUESTION, "req-6")

    assert result.status == Status.OK
    plan_step = next(s for s in result.trace if s.name == "link_plan")
    assert plan_step.error and plan_step.error.startswith("fallback")
    assert any(e.kind == "triple" for e in result.evidence)  # capitalised phrases still linked


def test_transaction_evidence_includes_the_counterparty(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = raw_result(
        txn_edges("T1", "C:TATASTEEL", "C:TATAMOTORS", "t1"),
        {"T1": {"nature": "Sale of goods", "amount_inr": 482000000.0, "fiscal_year": "FY2022-23"}},
    )
    plan = {**PLAN, "relation_types": ["PARTY_TO"]}
    _use(monkeypatch, Graph(raw, raw_result([])), _llm(plan=plan))
    result = GraphRAGPipeline().answer(
        "What related party transactions did Tata Steel report?", "r7"
    )

    txn = next(e for e in result.evidence if e.kind == "triple")
    assert "Tata Steel Limited" in txn.text and "Tata Motors Limited" in txn.text
    assert "₹ 48.20 crore" in txn.text
    assert txn.ref_id == "t1-r,t1-c"


def test_abstention_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, Graph(HOP1, HOP2), _llm(answer=NOT_FOUND))
    assert GraphRAGPipeline().answer(QUESTION, "req-8").status == Status.ABSTAINED


def test_never_raises_when_everything_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(question: str, k: int, filters=None) -> list[dict]:
        raise RuntimeError("index missing")

    _use(monkeypatch, Graph(GraphQueryError("down"), GraphQueryError("down")))
    monkeypatch.setattr(rag_mod, "vector_search", boom)
    result = GraphRAGPipeline().answer(QUESTION, "req-9")
    assert result.status == Status.ERROR
    assert result.trace[-1].error is not None


def test_spend_cap_becomes_an_error_result(monkeypatch: pytest.MonkeyPatch) -> None:
    from server.llm.gateway import SpendCapExceeded

    def capped(req):  # type: ignore[no-untyped-def]
        raise SpendCapExceeded("cap")

    _use(monkeypatch, Graph(), capped)
    result = GraphRAGPipeline().answer(QUESTION, "req-10")
    assert result.status == Status.ERROR
    assert result.trace[-1].error == "spend_cap"


def test_graphrag_is_registered_alongside_rag() -> None:
    from server.pipelines.base import REGISTRY, load_all

    load_all()
    assert {"rag", "graphrag"} <= set(REGISTRY)


def test_global_question_uses_statistics_and_never_touches_the_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.graph.stats import StatItem
    from server.pipelines.graphrag import global_mode as gm

    pack = [
        StatItem(topic="COVERAGE", text="The dataset has 26 documents covering 4 companies."),
        StatItem(topic="IN_SECTOR", text="Sector Automobiles: 2 companies tracked."),
    ]
    monkeypatch.setattr(gm, "dataset_stats_pack", lambda: pack)
    graph = Graph()
    answer = {
        "answer_type": "text",
        "answer_short": "Automobiles",
        "answer_long": "Automobiles has two companies [E2].",
        "citations": [{"evidence_id": "E2", "quote": "Sector Automobiles: 2 companies tracked."}],
    }
    _use(monkeypatch, graph, _llm(plan={**PLAN, "mentions": [], "is_global": True}, answer=answer))

    result = GraphRAGPipeline().answer("Which sector has the most companies?", "req-global")

    assert result.status == Status.OK
    assert graph.expand_calls == []
    assert [e.kind for e in result.evidence] == ["summary", "summary"]
    assert "global_stats" in _names(result) and "expand_hop(hop 1)" not in _names(result)
    assert result.citations[0].doc_id == ""  # statistics have no source page


def test_global_question_without_statistics_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    from server.pipelines.graphrag import global_mode as gm

    monkeypatch.setattr(gm, "dataset_stats_pack", lambda: [])
    _use(monkeypatch, Graph(), _llm(plan={**PLAN, "mentions": [], "is_global": True}))
    result = GraphRAGPipeline().answer("Which sector has the most companies?", "req-global-2")
    assert (
        next(s for s in result.trace if s.name == "fallback").input_summary
        == "no_global_statistics"
    )
    assert [e.kind for e in result.evidence] == ["chunk"]
