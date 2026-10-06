import json
import logging
import os
from pathlib import Path

import numpy as np

from server.embed.provider import MODEL_NAME, embed_texts
from server.embed.query import embed_query

logger = logging.getLogger(__name__)

DATA_DIR = "data/vectors"
CHUNKS_DIR = Path("data/chunks")


def _load_all_chunks() -> list[dict]:
    """Chunks live as data/chunks/{doc_id}_chunks.json (written by
    chunk_all()), not a SQLite table -- there is no `chunks` table in the
    schema."""
    chunks: list[dict] = []
    for f in sorted(CHUNKS_DIR.glob("*_chunks.json")):
        chunks.extend(json.loads(f.read_text()))
    return chunks


def build_vector_index() -> None:
    logger.info("Initializing Vector Index Builder (NumPy Fallback Mode)...")

    os.makedirs(DATA_DIR, exist_ok=True)
    index_path = os.path.join(DATA_DIR, f"{MODEL_NAME}_index.npz")

    logger.info("Loading chunks from data/chunks/...")
    chunks = [c for c in _load_all_chunks() if c.get("text")]

    if not chunks:
        logger.warning("No valid chunks found to embed. Skipping index build.")
        return

    chunk_ids = [str(c["chunk_id"]) for c in chunks]
    texts = [str(c["text"]) for c in chunks]

    logger.info(f"Embedding {len(texts)} chunks using {MODEL_NAME}...")
    vectors = embed_texts(texts, is_query=False)

    logger.info(f"Compressing and saving vector index to {index_path}...")
    np.savez_compressed(
        index_path, chunk_ids=np.array(chunk_ids), vectors=np.array(vectors, dtype=np.float32)
    )

    logger.info("Vector index successfully built!")


def search_vector_index(
    query: str, k: int = 10, allowed_doc_prefixes: set[str] | None = None
) -> list[tuple[str, float]]:
    index_path = os.path.join(DATA_DIR, f"{MODEL_NAME}_index.npz")
    if not os.path.exists(index_path):
        raise FileNotFoundError("Vector index not found. Run build_vector_index() first.")

    logger.debug(f"Loading vector index from {index_path}")
    data = np.load(index_path)
    chunk_ids = data["chunk_ids"]
    vectors = data["vectors"]

    q_vec = embed_query(query)
    q_vec_np = np.array(q_vec, dtype=np.float32)

    # Compute dot product (since embeddings are L2 normalized, dot product == cosine similarity)
    similarities = np.dot(vectors, q_vec_np)
    if allowed_doc_prefixes is not None:
        allowed = np.array([str(c).split("-", 1)[0] in allowed_doc_prefixes for c in chunk_ids])
        similarities = np.where(allowed, similarities, -np.inf)

    if len(similarities) <= k:
        top_k_indices = np.argsort(similarities)[::-1]
    else:
        # np.argpartition is significantly faster than argsort for large arrays
        top_k_indices = np.argpartition(similarities, -k)[-k:]
        # Sort just the top K
        top_k_indices = top_k_indices[np.argsort(similarities[top_k_indices])[::-1]]

    results = []
    for idx in top_k_indices:
        if np.isneginf(similarities[idx]):
            continue
        results.append((str(chunk_ids[idx]), float(similarities[idx])))

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    build_vector_index()
