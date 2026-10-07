# ADR-0013: GraphRAG Parameters, Fallbacks and Known Gaps

The phase plan names this record `0012-graphrag-params.md`; `0012` was already taken by the reranker ADR, so this is `0013`.

## Status
Accepted for the implementation. **Parameters are untuned**: they are the plan's starting values. Tuning on dev (plan Step 12) needs a reachable TigerGraph and has not happened. See "Verification status".

## Context
GraphRAG is the middle point of the comparison: structure without autonomy. One helper-model call plans the retrieval, a fixed bounded expansion runs, and one call answers. It shares the answer prompt, citation validation, budget and rerank decision with RAG (ADR-0012) so differences between the pipelines come from retrieval, not plumbing.

## Parameters (`config/pipeline.yaml: graphrag`)

| Parameter | Value | Why |
| --- | --- | --- |
| `max_hops` | 2 | Plan start value. Enough for "director of A also on B" (company -> person -> company). |
| `fanout_hop1` / `fanout_hop2` | 50 / 15 | Plan start values. Hop 2 is smaller because it fans out from every hop-1 neighbour. Newest fiscal year is kept first. |
| `max_triples` | 150 | Plan start value. A transaction and its counterparty edge count as one unit and are never split by the cap. |
| `min_per_relation` | 5 | Reserved slots per requested relation so an abundant type cannot crowd out another. |
| `triple_budget_share` | 0.6 | Triples get up to 60% of the shared evidence budget; linked chunks get the rest, plus any unused triple share. The first lever if GraphRAG underperforms RAG on single-fact questions. |
| `linked_chunks` | 6 | Chunks kept after similarity ranking (and reranking when enabled). |
| `link_min_score` / `link_score_gap` | 85 / 5 | A mention links only if `token_set_ratio` >= 85; a runner-up within 5 points makes it `ambiguous` and keeps up to two candidates. |
| `hub_degree_percentile` / `hub_min_degree` | 99 / 25 | An entity is a hub only if above the 99th percentile **and** above an absolute floor of 25. The floor stops a small graph from flagging its own busiest company. |
| `gsql_timeout_seconds` | 10 | Per `expand_hop` / `chunks_for_entities` call. |
| `global_enabled` | true | Global questions use the statistics pack. |

## Decisions that differ from the plan

1. **New `expand_hop` query instead of `entity_neighbors`.** `entity_neighbors` returns bare `id|type|id` strings with no edge attributes, so it cannot supply the `doc_id/page/quote` that triples need for citations. `expand_hop` prints the edges themselves. `entity_neighbors` is untouched.
2. **Fiscal-year filtering, per-seed fan-out and ranking run in Python**, not inside GSQL. Per-seed caps inside a single `ACCUM` are not reliable (accumulator reads are snapshot-based), and Python is unit-testable. GSQL keeps only a soft row bound.
3. **Hops are two calls, not one `hops=2` call**, so hop 2 can start from a hub-free, fan-out-capped frontier chosen in Python.
4. **Hub degree comes from the resolver's `merge_log`** (mentions per entity = fact-edge degree), not `v.outdegree()` in GSQL, whose availability the plan flags as "Verify". MENTIONS edges to chunks are deliberately excluded because expansion never walks them.
5. **Vertex ids are passed as `SET<STRING>`.** pyTigerGraph encodes untyped `SET<VERTEX>` only from `(id, type)` tuples; bare ids (what the existing `neighbors` / `chunks_for_entities` wrappers sent) are encoded without a type. Those wrappers, and `path_between`, now send typed tuples.
6. **Global questions use a statistics pack computed from the accepted records** in Turso, not new GSQL accumulator queries. It reflects exactly what built the graph and is testable offline. Every item states its basis and a coverage item states which companies have data.
7. **Sector mentions** are matched against sector names and expand to that sector's companies from `companies.yaml`, because `Sector` vertices and `IN_SECTOR` edges are not loaded by the current loader.

## Fallbacks and error handling
Every fallback records its reason in the trace (`fallback` step, `fallback=vector`), so failures can be counted.

| Situation | Behaviour |
| --- | --- |
| Helper call fails / unparseable | Capitalised-phrase mentions, all relation types, only a year written in the question. |
| No entity links | Same vector retrieval RAG uses (`retrieve_chunks`), so GraphRAG is never worse than RAG merely because the graph was silent. |
| `expand_hop` fails | Retried once with half the fan-out; then vector fallback. This includes failing to open the TigerGraph connection. |
| Empty subgraph | Vector fallback. |
| `chunks_for_entities` / vector index fails | Triples are still used; linked text is skipped and the error traced. |
| Spend cap | Propagates to an `error` result (not swallowed by the fallback). |

## Verification status (read this before trusting any number)
- **Unit and fixture-graph tests pass** (`tests/unit/test_*`, `tests/integration/test_graphrag_fixture.py`) with the GSQL runner, LLM calls and indexes replaced by fixtures shaped like TigerGraph's output.
- **`expand_hop.gsql` has never been installed or run.** The TigerGraph Cloud token endpoint returned HTTP 500 for the whole session. The query follows the syntax of the repo's installed queries, but undirected multi-type edge patterns (`-((A|B):e)-`), filtering with `e.type IN <set>`, and printing a `SetAccum<EDGE>` are unverified. Install it with `hl build-graph --from schema` and run one question; if it fails to compile, the pipeline degrades to the vector fallback rather than erroring.
- **A real end-to-end run with the cluster down** (`hl ask ... --pipeline graphrag`) exercised the actual entity index, vector index, Groq and the connection-failure fallback, and answered correctly. A five-question dev run fell back to vector retrieval on all five (`expansion_failed`). Those scores describe the fallback, not GraphRAG, and were deliberately not stored.
- **Not done:** `hl eval` on dev/test against a live graph, tuning, the test-split run, and the multi-hop paired comparison (`hl compare`). Exit criteria 1-4 of the phase are therefore open. The test split must be run once, after tuning, on a working graph.
- **Dataset caveat:** the local store has 3 company entities, 27 people and no audit-firm entities, no related-party records and no multi-hop questions in `questions_v1.jsonl`. Even with a live graph, the current eval set cannot show GraphRAG beating RAG on multi-hop. The question set needs the multi-hop / temporal / global categories first.

## Deferred
- **Community summaries (plan Step 11, optional).** Needs a `Community` vertex, a `HAS_MEMBER` edge and a vector attribute (a schema change), plus community detection whose availability on this TigerGraph edition is unverified. Revisit only if the statistics pack loses on the global category.

## Consequences
- Phase 7 reuses `link_mention` (`find_entity`), `expand` (`neighbors`), `linked_text` (`search_text`), `serialize`, and the shared final answer.
- Tuning knobs and their intended levers: `entity_link_error` -> `link_min_score`, aliases, the mention prompt; `missed_hop` -> `fanout_hop2`, `min_per_relation`; `retrieval_miss` with hubs -> `hub_*`; `temporal_error` -> the year filter; GraphRAG worse than RAG on single-fact -> raise the chunk share (`triple_budget_share`).

## Update (2026-10-07)

The dataset caveat above is now partly resolved: the live graph works (see
`docs/test-plan.md`'s "Live TigerGraph verification"), and a real multi-hop question
(`uv run hl ask "Which director sits on the boards of both Tata Motors and Tata Steel?"
--pipeline graphrag`) completed the full graph path — `link_plan → link_entities →
choose_relations → expand_hop(hop 1) → expand_hop(hop 2) → linked_text → final_answer` — and
cited graph triples, not a vector fallback. The dataset still has no `multi_hop`/`temporal`/
`global` questions in `questions_v1.jsonl`, and no `hl eval`/`hl compare` run has been made
against the test split (blocked on the Groq daily rate limit during this verification session).
Exit criteria 1-4 remain open for that reason, not because the graph doesn't work.
