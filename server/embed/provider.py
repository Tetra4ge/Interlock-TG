import logging

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Use a lightweight, highly-effective local embedding model
# all-MiniLM-L6-v2 produces 384-dimensional embeddings, ideal for TigerGraph
MODEL_NAME = "all-MiniLM-L6-v2"
DIMENSION = 384

_model_instance = None

def get_model() -> SentenceTransformer:
    global _model_instance
    if _model_instance is None:
        logger.info(f"Loading embedding model: {MODEL_NAME}")
        _model_instance = SentenceTransformer(MODEL_NAME)
    return _model_instance

def embed_texts(texts: list[str], is_query: bool = False) -> list[list[float]]:
    """
    Returns embeddings for the provided texts.
    For all-MiniLM-L6-v2, no specific query prefix is required, but normalization is recommended.
    """
    model = get_model()
    # SentenceTransformers outputs numpy arrays; we convert to Python lists for DB insertion.
    embeddings = model.encode(texts, batch_size=32, normalize_embeddings=True)
    return embeddings.tolist()
