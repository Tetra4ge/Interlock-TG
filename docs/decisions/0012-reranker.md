# ADR-0012: Cross-Encoder Reranker for Retrieval

## Status
Accepted (provisional). Enabled in `config/pipeline.yaml` (`retrieval.use_reranker: true`).
The 30-question recall@8 comparison from the phase doc has not been run; the decision rests
on a 10-question smoke check (see Consequences). Revisit once the labeled recall set exists.

## Context
Phase 3 built dense (bi-encoder) vector search over chunk embeddings
(`server/embed/`). A cross-encoder reranker reads `(question, chunk)`
together and scores relevance more precisely than a bi-encoder, at the cost
of extra latency -- it's only run on vector search's already-narrowed
candidate set (`rag_top_k`, default top 20). Per `phases/phase-04-rag-baseline.md`
§4.4 Step 11, this is a hold-across-pipelines decision: if enabled, RAG and
GraphRAG's linked-chunk ranking must both use it, or comparisons between
pipelines in Phase 5's eval are no longer apples-to-apples.

## Options Considered
1. **No reranker.** Simpler, faster, cheaper. Risks weaker recall@8 on
   questions where the bi-encoder ranks a relevant chunk just outside the
   evidence budget.
2. **Local cross-encoder via `sentence-transformers`** (`CrossEncoder`,
   already a project dependency). No API cost, runs on commodity hardware,
   adds one extra scoring pass over ~`rag_top_k` candidates.
3. **Hosted rerank API.** Adds a network dependency and per-call cost for
   no clear quality gain at this corpus size; ruled out to keep the $0
   Groq-free-tier cost profile from `config/models.yaml`.

## Decision
Implemented as **Option 2**: `server/pipelines/common/rerank.py`, using
`cross-encoder/ms-marco-MiniLM-L-6-v2`, wired into `server/pipelines/rag.py`
behind `config/pipeline.yaml`'s `retrieval.use_reranker` flag (default
`false`). The component is complete and ready to A/B; the experiment itself
is deferred (see Status).

## How to run the deferred experiment
1. Ingest and chunk a real set of documents (`hl fetch`, `hl parse`,
   `hl chunk`) and build the vector index (`hl build-graph` through the
   `embed` step, or `build_vector_index()` directly).
2. Reuse the 30 recall-test questions from Phase 3
   (`server/embed/recall_test.py`).
3. Run each question through `vector_search()` with
   `retrieval.use_reranker: false`, then again with it flipped to `true`
   (and `rerank_top_k` applied), and compare recall@8.
4. If the reranker clearly improves recall@8 and the added latency
   (`rerank` trace step) is acceptable, flip `use_reranker` to `true` in
   `config/pipeline.yaml` for both RAG and GraphRAG, update this ADR's
   Status to Accepted, and record the numbers here.

## Smoke check (provisional evidence)
Same 10 questions, cloud TigerGraph, reranker off vs on:
- Reranker off: 3 of 8 answerable questions answered with correct citations; one answer cited the wrong company.
- Reranker on (and budget 4000): 5 of 8 answerable questions answered correctly; the wrong-company
  answers were removed by company and fiscal-year scoping. Added latency: roughly 10-100 s per question
  on the first call in a process (CrossEncoder load), about 10 s after that.
The 10-question run is not a recall@8 measurement, so this is not the phase's acceptance test.

## Consequences
- `rag.py` already logs a `rerank` trace step with latency whenever the
  flag is on, so the cost of turning it on is visible in `traces` without
  further instrumentation.
- Until Accepted, RAG's evidence set is bi-encoder top-`rag_top_k` only.
