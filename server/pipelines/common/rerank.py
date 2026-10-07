import logging

from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)

# A small, widely-used passage reranker; swap via ADR-0012 if the recall
# comparison (once real documents + a live graph are available) favors
# something else.
MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

_model_instance: CrossEncoder | None = None


def get_model() -> CrossEncoder:
    global _model_instance
    if _model_instance is None:
        logger.info(f"Loading reranker model: {MODEL_NAME}")
        _model_instance = CrossEncoder(MODEL_NAME)
    return _model_instance


def rerank(question: str, hits: list[dict]) -> list[dict]:
    """Cross-encoder reranking: reads (question, chunk) together and scores
    relevance -- slower but more precise than the bi-encoder vector search.
    Only run on vector search's already-narrowed candidate set (top ~k*3)."""
    if not hits:
        return hits
    model = get_model()
    pairs = [(question, h.get("text", "")) for h in hits]
    scores = model.predict(pairs)
    scored = sorted(zip(hits, scores, strict=True), key=lambda x: x[1], reverse=True)
    return [h for h, _ in scored]


def rerank_fused(question: str, hits: list[dict], top_k: int) -> list[dict]:
    """Cross-encoder order fused with the retrieval order, so a reranker slip
    cannot discard a chunk both rankings liked. Shared by every pipeline that
    reranks (ADR-0012: reranking must hold across pipelines)."""
    from server.pipelines.common.fusion import reciprocal_rank_fusion

    reranked = rerank(question, hits)
    order = reciprocal_rank_fusion(
        [[(h["chunk_id"], 0.0) for h in hits], [(h["chunk_id"], 0.0) for h in reranked]],
        k_out=top_k,
    )
    by_id = {h["chunk_id"]: h for h in hits}
    return [by_id[cid] for cid, _ in order]
