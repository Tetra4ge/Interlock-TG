from typing import Any

import pytest

from server.pipelines import rag as rag_mod  # noqa: F401  (registers "rag")
from server.pipelines.agent import loop as loop_mod
from server.pipelines.agent import verifier as verifier_mod
from server.pipelines.agent.tools import find_entity as fe_mod
from server.pipelines.agent.tools import graph_query as gq_mod
from server.pipelines.agent.tools import neighbors as nb_mod
from server.pipelines.agent.tools import search_text as st_mod
from server.pipelines.common import answer as answer_mod
from server.pipelines.common import tracer as tracer_mod
from server.pipelines.graphrag import expand as expand_mod
from tests.integration.agent_harness import NAMES, FakeConn, Graph, ScriptedLLM


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch) -> ScriptedLLM:
    scripted = ScriptedLLM()
    monkeypatch.setattr(loop_mod, "call_llm", scripted)
    monkeypatch.setattr(answer_mod, "call_llm", scripted)
    monkeypatch.setattr(verifier_mod, "call_llm", scripted)
    return scripted


@pytest.fixture
def make_graph(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(tracer_mod, "connect", lambda: FakeConn())
    monkeypatch.setattr(expand_mod, "hub_ids", lambda *a, **k: set())
    monkeypatch.setattr(
        nb_mod, "entity_names", lambda ids: {i: NAMES[i] for i in ids if i in NAMES}
    )
    monkeypatch.setattr(
        gq_mod, "entity_names", lambda ids: {i: NAMES[i] for i in ids if i in NAMES}
    )
    monkeypatch.setattr(
        fe_mod,
        "find_candidates",
        lambda name, kind, limit: [
            {"entity_id": eid, "canonical_name": n, "kind": k, "match": 100}
            for eid, (n, k) in NAMES.items()
            if name.lower() in n.lower()
        ][:limit],
    )

    def build(*expand_responses: Any) -> Graph:
        graph = Graph(*expand_responses)
        monkeypatch.setattr(expand_mod, "run_installed_strict", graph.expand)
        monkeypatch.setattr(gq_mod, "run_installed_strict", graph.query)
        return graph

    return build


@pytest.fixture
def vector(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    def install(chunks: list[dict]) -> None:
        monkeypatch.setattr(st_mod, "vector_search", lambda q, k, filters=None: chunks)
        monkeypatch.setattr(st_mod, "_excluded_doc_ids", lambda: set())
        monkeypatch.setattr(st_mod.RETRIEVAL, "use_reranker", False)

    return install


@pytest.fixture(autouse=True)
def no_embedding_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evidence relevance scoring uses the sentence-transformer; tests must not load it."""
    from server.pipelines.agent import pipeline as agent_pipeline

    monkeypatch.setattr(agent_pipeline, "question_similarity", lambda q, texts: [0.0] * len(texts))
