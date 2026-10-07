import pytest

from server.graph.queries import GraphQueryError
from server.pipelines.config import GraphRAGConfig
from server.pipelines.graphrag import linked_text as lt
from tests.unit.graphrag_fixtures import triple

CFG = GraphRAGConfig(linked_chunks=2)


def _v(chunk_id: str, text: str = "text", **attrs: object) -> dict:
    return {
        "v_id": chunk_id,
        "v_type": "Chunk",
        "attributes": {"doc_id": "doc-1", "text": text, "page_start": 3, "page_end": 3, **attrs},
    }


def _patch(monkeypatch: pytest.MonkeyPatch, chunks: list[dict], scores: dict[str, float]) -> None:
    monkeypatch.setattr(
        lt, "chunks_for_entities_strict", lambda ids, limit, t=None: [{"Chunks": chunks}]
    )
    monkeypatch.setattr(
        lt, "score_chunks", lambda q, ids: {i: scores[i] for i in ids if i in scores}
    )
    monkeypatch.setattr(lt.RETRIEVAL, "use_reranker", False)


def test_parse_chunks_reads_vertex_objects() -> None:
    out = lt.parse_chunks(
        [{"Chunks": [_v("c1", "hello", fiscal_year="FY2023-24"), {"v_id": "c2"}, "x"]}]
    )
    assert out == [
        {
            "chunk_id": "c1",
            "doc_id": "doc-1",
            "text": "hello",
            "page_start": 3,
            "page_end": 3,
            "fiscal_year": "FY2023-24",
        }
    ]
    assert lt.parse_chunks(None) == []
    assert lt.parse_chunks([{"Chunks": None}]) == []


def test_entities_are_linked_first_then_hop1_neighbours_only() -> None:
    ts = [
        triple(src="P:1", dst="C:1", edge_id="a", hop=1),
        triple(src="P:2", dst="C:9", edge_id="b", hop=2),
        triple("AUDITED_BY", "C:1", "A:1", edge_id="c", hop=1),
    ]
    assert lt.entity_ids_for_text(["C:1"], ts) == ["C:1", "P:1", "A:1"]


def test_sector_and_transaction_ids_are_not_sent_to_the_graph() -> None:
    ts = [triple("IN_SECTOR", "C:1", "Automobiles", edge_id="s")]
    assert lt.entity_ids_for_text(["Automobiles", "C:1"], ts) == ["C:1"]


def test_entity_list_is_capped() -> None:
    ts = [triple(src=f"P:{i}", dst="C:1", edge_id=f"e{i}") for i in range(200)]
    assert len(lt.entity_ids_for_text(["C:1"], ts)) == lt.MAX_ENTITIES


def test_chunks_are_ranked_by_similarity_and_capped(
    monkeypatch: pytest.MonkeyPatch, tracer
) -> None:  # type: ignore[no-untyped-def]
    chunks = [_v("c1"), _v("c2"), _v("c3")]
    _patch(monkeypatch, chunks, {"c1": 0.2, "c2": 0.9, "c3": 0.5})
    out = lt.linked_text("q", ["C:1"], [], set(), tracer, CFG)
    assert [c["chunk_id"] for c in out] == ["c2", "c3"]


def test_excluded_documents_and_other_years_are_dropped(
    monkeypatch: pytest.MonkeyPatch, tracer
) -> None:  # type: ignore[no-untyped-def]
    chunks = [
        _v("keep", fiscal_year="FY2023-24"),
        _v("old", fiscal_year="FY2021-22"),
        _v("bad", doc_id="excluded-doc", fiscal_year="FY2023-24"),
        _v("undated"),
    ]
    _patch(monkeypatch, chunks, {"keep": 0.9, "old": 0.9, "bad": 0.9, "undated": 0.1})
    out = lt.linked_text(
        "q", ["C:1"], ["FY2023-24"], {"excluded-doc"}, tracer, GraphRAGConfig(linked_chunks=5)
    )
    assert [c["chunk_id"] for c in out] == ["keep", "undated"]


def test_graph_failure_is_not_fatal_and_is_traced(monkeypatch: pytest.MonkeyPatch, tracer) -> None:  # type: ignore[no-untyped-def]
    def boom(ids, limit, t=None):  # type: ignore[no-untyped-def]
        raise GraphQueryError("chunks_for_entities: timeout")

    monkeypatch.setattr(lt, "chunks_for_entities_strict", boom)
    assert lt.linked_text("q", ["C:1"], [], set(), tracer, CFG) == []
    assert "timeout" in (tracer.steps[-1].error or "")


def test_missing_vector_index_is_not_fatal(monkeypatch: pytest.MonkeyPatch, tracer) -> None:  # type: ignore[no-untyped-def]
    _patch(monkeypatch, [_v("c1")], {})

    def missing(q, ids):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("Vector index not found")

    monkeypatch.setattr(lt, "score_chunks", missing)
    assert lt.linked_text("q", ["C:1"], [], set(), tracer, CFG) == []


def test_no_entities_makes_no_graph_call(monkeypatch: pytest.MonkeyPatch, tracer) -> None:  # type: ignore[no-untyped-def]
    def fail(*a, **k):  # type: ignore[no-untyped-def]
        raise AssertionError("graph must not be called")

    monkeypatch.setattr(lt, "chunks_for_entities_strict", fail)
    assert lt.linked_text("q", [], [], set(), tracer, CFG) == []
