# ADR-0011: Vector Search Implementation

## Status
Accepted

## Context
We need to run nearest-neighbor search across Chunk embeddings to power GraphRAG. While some newer versions of TigerGraph support native Vector Attributes and `vectorSearch()`, deploying this locally in Docker can sometimes be flaky if the correct plugins or vector endpoints are not perfectly aligned. To ensure maximum compatibility and zero-configuration robustness, we need a reliable vector retrieval system.

## Decision
We will implement a **NumPy-based local fallback index** for vector search. Embeddings will be generated via `sentence-transformers` and cached to disk in `data/vectors/` keyed by `chunk_id`.

## Rationale
- **Compatibility**: Runs instantly on any machine (Mac, Linux, Windows) without complex TigerGraph C++ vector plugin dependencies.
- **Speed**: NumPy matrix multiplication for cosine similarity (with L2-normalized embeddings) easily handles tens of thousands of vectors in milliseconds. It is perfectly optimized via underlying BLAS/LAPACK routines, which is more than enough for our current corpus scale.
- **Simplicity**: No need for FAISS, which requires heavy C++ compilation. `np.dot` is built-in to our existing environment.

## Consequences
- `embed/index.py` will save the embeddings as an `.npz` archive.
- `graph/queries.py`'s `vector_search` function will read from this local `.npz` archive to retrieve Top-K `chunk_id`s, then fetch the full text chunks directly from TigerGraph using native `conn.getVerticesById` calls.
- This hybrid approach keeps unstructured search local and structured graph traversal in TigerGraph.
