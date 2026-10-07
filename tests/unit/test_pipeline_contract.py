"""Pipeline contract tests — all three pipelines must return a valid AnswerResult.

These run offline with no LLM or TigerGraph connection. Stubs are minimal: just
enough for the pipeline to complete one question without raising. The assertions
focus on the *contract* (shape, type-safety, invariants) rather than retrieval
quality; correctness is tested separately in the fixture integration tests.

All tests are unit-marked (the default) so they run in CI without credentials.
"""

import json

import pytest

from server.llm.models import LLMResponse
from server.pipelines import rag as rag_mod
from server.pipelines.agent import loop as loop_mod
from server.pipelines.agent import pipeline as agent_pipeline_mod
from server.pipelines.agent import verifier as verifier_mod
from server.pipelines.agent.pipeline import AgentPipeline
from server.pipelines.agent.tools import find_entity as fe_mod
from server.pipelines.agent.tools import search_text as st_mod
from server.pipelines.common import answer as answer_mod
from server.pipelines.common import tracer as tracer_mod
from server.pipelines.graphrag import expand as expand_mod
from server.pipelines.graphrag import linked_text as lt_mod
from server.pipelines.graphrag import linking as linking_mod
from server.pipelines.graphrag import pipeline as graphrag_pipe_mod
from server.pipelines.graphrag.pipeline import GraphRAGPipeline
from server.pipelines.models import AnswerResult, AnswerType, Status

# ── shared fixture data ──────────────────────────────────────────────────────

QUESTION = "Who audited Bajaj Finance in FY2023-24?"
DOC_ID = "b" * 24
CHUNK = {
    "chunk_id": "chunk-c1",
    "doc_id": DOC_ID,
    "text": "The statutory auditor for FY2023-24 is S R B C & CO LLP.",
    "page_start": 87,
    "page_end": 87,
    "section": "auditor",
    "fiscal_year": "FY2023-24",
}
ANSWER_JSON = json.dumps(
    {
        "answer_type": "entity",
        "answer_short": "S R B C & CO LLP",
        "answer_long": "S R B C & CO LLP audited Bajaj Finance in FY2023-24 [E1].",
        "citations": [
            {
                "evidence_id": "E1",
                "quote": "The statutory auditor for FY2023-24 is S R B C & CO LLP.",
            }
        ],
    }
)
VERDICT_JSON = json.dumps(
    {
        "claims": [
            {
                "claim": "S R B C & CO LLP is the auditor",
                "verdict": "SUPPORTED",
                "evidence_labels": ["E1"],
            }
        ]
    }
)
# A plan with no mentions forces GraphRAG to fall back to vector retrieval
# — the simplest path through the pipeline that still exercises the contract.
EMPTY_PLAN_JSON = json.dumps(
    {"mentions": [], "relation_types": [], "fiscal_years": [], "is_global": False}
)


class _FakeConn:
    def execute(self, sql: str, params: list | None = None) -> None:
        return None

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


def _llm_returning(payload: str):  # type: ignore[no-untyped-def]
    def call(req: object) -> LLMResponse:
        return LLMResponse(content=payload, tokens_in=100, tokens_out=20)

    return call


def _assert_contract(result: AnswerResult, pipeline: str) -> None:
    """Verify the AnswerResult contract that every pipeline must satisfy."""
    assert isinstance(result, AnswerResult), (
        f"{pipeline}: must return AnswerResult, got {type(result)}"
    )
    assert result.pipeline == pipeline, (
        f"pipeline field: expected {pipeline!r}, got {result.pipeline!r}"
    )
    assert result.question == QUESTION
    assert result.status in list(Status), f"invalid status {result.status!r}"
    assert result.answer_type in list(AnswerType), f"invalid answer_type {result.answer_type!r}"
    assert isinstance(result.answer_short, str)
    assert isinstance(result.answer_long, str)
    assert isinstance(result.citations, list)
    assert isinstance(result.evidence, list)
    assert isinstance(result.trace, list)
    assert len(result.trace) > 0, "trace must not be empty"
    assert result.usage.tokens_in >= 0
    assert result.usage.tokens_out >= 0
    assert result.usage.latency_ms >= 0
    assert result.usage.llm_calls >= 0
    assert result.usage.tool_calls >= 0
    for c in result.citations:
        assert len(c.doc_id) > 0, "citation.doc_id must be non-empty"
        assert c.page >= 0, f"citation.page must be >= 0, got {c.page}"
    for e in result.evidence:
        assert e.kind in ("chunk", "triple", "tool_result", "summary"), (
            f"unknown evidence kind {e.kind!r}"
        )
        assert len(e.text) > 0, "evidence.text must be non-empty"


# ── RAG contract ─────────────────────────────────────────────────────────────


def test_rag_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracer_mod, "connect", lambda: _FakeConn())
    monkeypatch.setattr(rag_mod, "vector_search", lambda q, k, filters=None: [CHUNK])
    monkeypatch.setattr(rag_mod, "_excluded_doc_ids", lambda: set())
    monkeypatch.setattr(rag_mod.RETRIEVAL, "use_reranker", False)
    monkeypatch.setattr(answer_mod, "call_llm", _llm_returning(ANSWER_JSON))

    from server.pipelines.rag import RAGPipeline

    result = RAGPipeline().answer(QUESTION, "contract-rag")
    _assert_contract(result, "rag")
    assert result.status == Status.OK
    assert result.answer_short == "S R B C & CO LLP"
    assert result.usage.llm_calls >= 1


# ── GraphRAG contract (vector-fallback path) ─────────────────────────────────


def test_graphrag_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracer_mod, "connect", lambda: _FakeConn())
    # The plan returns no mentions → pipeline falls back to vector retrieval
    monkeypatch.setattr(linking_mod, "call_llm", _llm_returning(EMPTY_PLAN_JSON))
    monkeypatch.setattr(linking_mod, "entity_search", lambda text, kind=None, limit=5: [])
    monkeypatch.setattr(graphrag_pipe_mod, "entity_names", lambda ids: {})
    monkeypatch.setattr(graphrag_pipe_mod, "_excluded_doc_ids", lambda: set())
    monkeypatch.setattr(expand_mod, "hub_ids", lambda *a, **k: set())
    monkeypatch.setattr(
        lt_mod,
        "chunks_for_entities_strict",
        lambda ids, limit, t=None: [],
    )
    monkeypatch.setattr(lt_mod, "score_chunks", lambda q, ids: {})
    monkeypatch.setattr(lt_mod.RETRIEVAL, "use_reranker", False)
    monkeypatch.setattr(rag_mod, "vector_search", lambda q, k, filters=None: [CHUNK])
    monkeypatch.setattr(rag_mod, "_excluded_doc_ids", lambda: set())
    monkeypatch.setattr(rag_mod.RETRIEVAL, "use_reranker", False)
    monkeypatch.setattr(answer_mod, "call_llm", _llm_returning(ANSWER_JSON))

    result = GraphRAGPipeline().answer(QUESTION, "contract-graphrag")
    _assert_contract(result, "graphrag")
    assert result.status == Status.OK
    assert result.usage.llm_calls >= 1


# ── Agent contract (immediate-stop path: no tool calls) ──────────────────────


def test_agent_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    # stop_turn: the agent emits no tool calls and moves to final_answer immediately
    stop_response = LLMResponse(content="Ready: no tools needed.", tokens_in=200, tokens_out=10)

    monkeypatch.setattr(tracer_mod, "connect", lambda: _FakeConn())
    monkeypatch.setattr(loop_mod, "call_llm", lambda req: stop_response)
    monkeypatch.setattr(answer_mod, "call_llm", _llm_returning(ANSWER_JSON))
    monkeypatch.setattr(verifier_mod, "call_llm", _llm_returning(VERDICT_JSON))
    # Evidence relevance scoring uses sentence-transformer; skip it in unit tests
    monkeypatch.setattr(
        agent_pipeline_mod, "question_similarity", lambda q, texts: [0.0] * len(texts)
    )
    # Tool stubs are needed so imports don't fail even though tools are not called
    monkeypatch.setattr(st_mod, "vector_search", lambda q, k, filters=None: [CHUNK])
    monkeypatch.setattr(st_mod, "_excluded_doc_ids", lambda: set())
    monkeypatch.setattr(st_mod.RETRIEVAL, "use_reranker", False)
    monkeypatch.setattr(fe_mod, "find_candidates", lambda name, kind, limit: [])

    result = AgentPipeline().answer(QUESTION, "contract-agent")
    _assert_contract(result, "agent")
    assert result.status in (Status.OK, Status.ABSTAINED)
    assert result.usage.llm_calls >= 1
    # no tools were called
    assert result.usage.tool_calls == 0
