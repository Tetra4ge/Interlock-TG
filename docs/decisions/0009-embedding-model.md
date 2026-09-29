# ADR-0009: Embedding Model Choice

## Status
Accepted

## Context
GraphRAG requires high-quality vector embeddings to perform semantic search over the text chunks (`Chunk` vertices) extracted from company documents. 
We need to select an embedding model that balances:
1. **Recall**: High accuracy at retrieving relevant chunks (Recall@10).
2. **Cost**: Preferably free (open-weight) to minimize batch indexing costs.
3. **Speed/Latency**: Fast to embed tens of thousands of chunks on commodity hardware.
4. **Dimension Size**: Smaller vectors (e.g., 384) are significantly cheaper to store in TigerGraph RAM than massive 1536d vectors (like OpenAI's).

## Options Considered
1. **OpenAI `text-embedding-3-small`**: 1536 dimensions. High recall, but incurs API costs and takes up 4x more RAM in the graph database.
2. **`all-MiniLM-L6-v2` (Sentence-Transformers)**: 384 dimensions. Completely free, runs locally, extremely fast, very low memory footprint in TigerGraph.

## Decision
We will use **`all-MiniLM-L6-v2`** running locally via the `sentence-transformers` library. 

## Rationale
- **Dimension Efficiency**: At 384 dimensions, the TigerGraph vector index will comfortably fit in memory, maximizing performance while minimizing infrastructure costs.
- **Cost**: Zero API costs for bulk processing the entire corpus.
- **Recall**: For standard English financial text, `all-MiniLM-L6-v2` provides excellent zero-shot retrieval performance. Cosine similarity performs flawlessly given `normalize_embeddings=True`.

## Consequences
- The `Chunk` vertex in TigerGraph will need a vector attribute: `embedding LIST<FLOAT>`.
- The dimension size for the TigerGraph schema change job will be fixed at `384`.
- We have added `sentence-transformers` and its native `torch` dependencies to our Python environment.
