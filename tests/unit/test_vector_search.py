import pytest

from server.graph import queries


def test_vector_search_reads_chunks_locally_without_tigergraph(monkeypatch: pytest.MonkeyPatch):
    chunks = [
        {
            "chunk_id": "c1",
            "text": "auditor",
            "fiscal_year": "FY2023-24",
            "company_id": "TATASTEEL",
        },
        {"chunk_id": "c2", "text": "other", "fiscal_year": "FY2022-23", "company_id": "TATASTEEL"},
    ]
    monkeypatch.setattr(queries, "_allowed_doc_ids", lambda _f: None)
    monkeypatch.setattr(queries, "search_vector_index", lambda *a, **k: [("c1", 0.9), ("c2", 0.5)])
    monkeypatch.setattr(queries, "keyword_search", lambda *a, **k: [("c1", 2.0)])
    monkeypatch.setattr(queries, "load_chunks", lambda _d: chunks)

    def _boom():
        raise AssertionError("vector_search must not call TigerGraph for chunk text")

    monkeypatch.setattr(queries, "get_tg_connection", _boom)

    hits = queries.vector_search("who is the auditor", k=5)
    assert [h["chunk_id"] for h in hits] == ["c1", "c2"]
    assert hits[0]["text"] == "auditor" and "score" in hits[0]


def test_vector_search_applies_year_filter(monkeypatch: pytest.MonkeyPatch):
    chunks = [
        {"chunk_id": "c1", "text": "a", "fiscal_year": "FY2023-24", "company_id": "X"},
        {"chunk_id": "c2", "text": "b", "fiscal_year": "FY2022-23", "company_id": "X"},
    ]
    monkeypatch.setattr(queries, "_allowed_doc_ids", lambda _f: None)
    monkeypatch.setattr(queries, "search_vector_index", lambda *a, **k: [("c1", 1.0), ("c2", 1.0)])
    monkeypatch.setattr(queries, "keyword_search", lambda *a, **k: [])
    monkeypatch.setattr(queries, "load_chunks", lambda _d: chunks)
    hits = queries.vector_search("q", k=5, filters={"fiscal_year": "FY2023-24"})
    assert [h["chunk_id"] for h in hits] == ["c1"]
