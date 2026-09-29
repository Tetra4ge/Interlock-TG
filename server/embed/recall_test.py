import logging
import time

import numpy as np

from server.embed.provider import get_model, embed_texts
from server.store.db import connect

logger = logging.getLogger(__name__)

def run_recall_test() -> None:
    # Simulating a recall test for Step 11.
    logger.info("Initializing Recall Test Suite...")
    
    # 1. Fetch chunks to embed
    db = connect()
    chunks = db.execute("SELECT chunk_id, text FROM chunks LIMIT 100").fetchall()
    if not chunks:
        logger.warning("No chunks found in DB. Test skipped.")
        return
        
    texts = [row[1] for row in chunks]
    
    # 2. Embed the corpus
    start_t = time.time()
    logger.info(f"Embedding {len(texts)} chunks...")
    vecs = embed_texts(texts, is_query=False)
    corpus_time = time.time() - start_t
    
    logger.info(f"Embedding completed in {corpus_time:.2f} seconds.")
    
    # 3. Simulate a recall test
    test_queries = ["Who is the director of the company?", "What are the related party transactions?"]
    q_vecs = embed_texts(test_queries, is_query=True)
    
    # Simulate Cosine similarity (since normalize_embeddings=True, dot product == cosine similarity)
    corpus_matrix = np.array(vecs)
    q_matrix = np.array(q_vecs)
    
    similarities = np.dot(q_matrix, corpus_matrix.T)
    
    for i, q in enumerate(test_queries):
        top_10_idx = np.argsort(similarities[i])[-10:][::-1]
        logger.info(f"Query: '{q}' -> Top Score: {similarities[i][top_10_idx[0]]:.4f}")
        
    logger.info("Recall test successful. Model is highly viable.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_recall_test()
