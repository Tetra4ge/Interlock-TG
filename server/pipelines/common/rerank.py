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
