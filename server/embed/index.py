import logging
import os

import numpy as np

from server.embed.provider import MODEL_NAME, embed_texts
from server.store.db import connect

logger = logging.getLogger(__name__)

DATA_DIR = "data/vectors"

def build_vector_index() -> None:
    logger.info("Initializing Vector Index Builder (NumPy Fallback Mode)...")
    db = connect()
    
    os.makedirs(DATA_DIR, exist_ok=True)
    index_path = os.path.join(DATA_DIR, f"{MODEL_NAME}_index.npz")
    
    logger.info("Fetching all chunks from DB...")
    chunks = db.execute(
        "SELECT chunk_id, text FROM chunks WHERE text IS NOT NULL AND text != ''"
    ).fetchall()
    
    if not chunks:
        logger.warning("No valid chunks found to embed. Skipping index build.")
        return
        
    chunk_ids = [str(c[0]) for c in chunks]
    texts = [str(c[1]) for c in chunks]
    
    logger.info(f"Embedding {len(texts)} chunks using {MODEL_NAME}...")
    vectors = embed_texts(texts, is_query=False)
    
    logger.info(f"Compressing and saving vector index to {index_path}...")
    np.savez_compressed(
        index_path, 
        chunk_ids=np.array(chunk_ids), 
        vectors=np.array(vectors, dtype=np.float32)
    )
    
    logger.info("Vector index successfully built!")

def search_vector_index(query: str, k: int = 10) -> list[tuple[str, float]]:
    index_path = os.path.join(DATA_DIR, f"{MODEL_NAME}_index.npz")
    if not os.path.exists(index_path):
        raise FileNotFoundError("Vector index not found. Run build_vector_index() first.")
        
    logger.debug(f"Loading vector index from {index_path}")
    data = np.load(index_path)
    chunk_ids = data["chunk_ids"]
    vectors = data["vectors"]
    
    q_vec = embed_texts([query], is_query=True)[0]
    q_vec_np = np.array(q_vec, dtype=np.float32)
    
    # Compute dot product (since embeddings are L2 normalized, dot product == cosine similarity)
    similarities = np.dot(vectors, q_vec_np)
    
    if len(similarities) <= k:
        top_k_indices = np.argsort(similarities)[::-1]
    else:
        # np.argpartition is significantly faster than argsort for large arrays
        top_k_indices = np.argpartition(similarities, -k)[-k:]
        # Sort just the top K
        top_k_indices = top_k_indices[np.argsort(similarities[top_k_indices])[::-1]]
        
    results = []
    for idx in top_k_indices:
        results.append((str(chunk_ids[idx]), float(similarities[idx])))
        
    return results

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    build_vector_index()
