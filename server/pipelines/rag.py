import time

from server.graph.queries import vector_search
from server.llm.gateway import SpendCapExceeded
from server.pipelines.base import register
from server.pipelines.common.answer import final_answer
from server.pipelines.common.budget import fit_to_budget
from server.pipelines.common.evidence import chunk_evidence
from server.pipelines.common.render import assign_labels
from server.pipelines.common.rerank import rerank_fused
from server.pipelines.common.result import build_result, elapsed_ms, error_result
from server.pipelines.common.scope import detect_filters
from server.pipelines.common.tracer import Tracer
from server.pipelines.config import RETRIEVAL
from server.pipelines.models import AnswerResult
from server.store.db import connect


def _excluded_doc_ids() -> set[str]:
    conn = connect()
    try:
        rows = conn.execute("SELECT doc_id FROM documents WHERE status = 'excluded'").fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


def retrieve_chunks(question: str, tr: Tracer) -> list[dict]:
    """Vector + keyword retrieval with optional rerank. Shared with GraphRAG's
    vector fallback so that fallback is exactly what RAG would have used."""
    t0 = time.perf_counter()
    excluded = _excluded_doc_ids()
    filters = detect_filters(question) or None
    hits = [
        h
        for h in vector_search(question, k=RETRIEVAL.rag_top_k, filters=filters)
        if h.get("doc_id") not in excluded
    ]
    tr.add(
        "retrieve",
        "vector_search",
        f"k={RETRIEVAL.rag_top_k} filters={filters or 'none'}",
        ", ".join(h.get("chunk_id", "") for h in hits[:10]),
        latency_ms=elapsed_ms(t0),
    )

    if RETRIEVAL.use_reranker:
        t1 = time.perf_counter()
        hits = rerank_fused(question, hits, RETRIEVAL.rerank_top_k)
        tr.add(
            "retrieve",
            "rerank",
            f"top_k={RETRIEVAL.rerank_top_k}",
            ", ".join(h.get("chunk_id", "") for h in hits[:10]),
            latency_ms=elapsed_ms(t1),
        )
    return hits


class RAGPipeline:
    name = "rag"

    def answer(self, question: str, request_id: str) -> AnswerResult:
        tr = Tracer(request_id, self.name)
        start = time.perf_counter()

        try:
            hits = retrieve_chunks(question, tr)
            items, provenance = chunk_evidence(hits)
            items = fit_to_budget(items, RETRIEVAL.evidence_token_budget)
            labels = assign_labels(items, provenance)

            model_answer, err = final_answer(tr, question, labels)
            if model_answer is None:
                return error_result(self.name, question, tr, err or "unknown_error", start)
            return build_result(self.name, question, tr, model_answer, labels, start)
        except Exception as e:
            reason = "spend_cap" if isinstance(e, SpendCapExceeded) else repr(e)
            return error_result(self.name, question, tr, reason, start)


register(RAGPipeline())
