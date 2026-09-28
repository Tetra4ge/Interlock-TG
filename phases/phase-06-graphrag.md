# Phase 6 — GraphRAG (single pass)

> **Accuracy note.** GSQL and query names are sketches; verify for your TigerGraph version. Community detection through TigerGraph's graph algorithm library depends on version/edition — verify before relying on it.

---

## 6.1 Overview

| Item | Detail |
| --- | --- |
| Goal | A single-pass GraphRAG pipeline: link question entities to graph nodes, expand a bounded, relevant subgraph, attach linked text, serialize it with provenance, and answer with the shared contract |
| Why | It is the middle point of the comparison — structure without autonomy. It should win on relational questions and clearly show where one fixed retrieval pass is not enough |
| Prerequisites | Phase 5 complete (runner, dev/test sets, RAG baseline) |
| Produces | `pipelines/graphrag/` package, GraphRAG dev/test runs, `docs/decisions/0012-graphrag-params.md`; optional global mode |
| PRD links | FR-22, FR-24, FR-25, FR-28 (optional) |
| TRD links | §6 (schema, indexes), §3.3 `graphrag`, §4.3 |

---

## 6.2 Concepts you will learn

### Entity linking
Mapping phrases in the question ("Example Industries", "Mr. Sharma") to node IDs. It is GraphRAG's single point of failure: if linking misses or picks the wrong node, everything after is wrong. So it gets its own trace step and its own failure label (`entity_link_error`).

### Local vs global retrieval
- **Local:** questions about specific entities → start from those nodes and expand.
- **Global:** questions about the whole corpus ("which sector…") → no single starting node; needs aggregation or precomputed summaries.
Single-pass GraphRAG handles local well; global needs either aggregation queries or community summaries.

### Bounded expansion and hub nodes
Some nodes connect to almost everything (a big audit firm, a sector node). Expanding through them floods the context with irrelevant triples. Solutions: exclude hub relation types unless asked for, cap per-node fan-out, rank triples by relevance, and cap the total.

### Graph-to-text serialization
The LLM reads text, so triples must become readable lines. Good serialization: consistent format, human-readable names (not IDs), time and value properties, and provenance for citations.

### Why single pass is a real limitation
GraphRAG decides *everything* it will retrieve before seeing any results. If the question needs "first find X, then based on X find Y, then sum Z", a fixed 2-hop expansion may miss it. That is exactly the gap the agent (Phase 7) should fill — and your evaluation should show it.

---

## 6.3 Files created

```
src/interlock/pipelines/graphrag/
├── __init__.py
├── prompts/
│   ├── link_v1.md          # mentions + relation types
├── linking.py              # mentions → entity ids
├── relations.py            # choose relation types to expand
├── expand.py               # bounded subgraph retrieval
├── rank.py                 # triple ranking and caps
├── serialize.py            # triples → evidence items
├── linked_text.py          # MENTIONS chunks ranked by similarity
├── pipeline.py             # GraphRAGPipeline
└── global_mode.py          # optional community summaries
tests/unit/test_linking.py, test_expand_caps.py, test_serialize.py
tests/integration/test_graphrag_fixture.py
docs/decisions/0012-graphrag-params.md
```

---

## 6.4 Step-by-step implementation

### Step 1 — Mention and relation extraction (`prompts/link_v1.md`)

One helper-model call returns both the entities mentioned and the relation types likely needed.

```
Identify what this question needs from a knowledge graph of Indian listed companies.

Graph relation types:
- DIRECTOR_OF (person → company; role, independent, from, to, fiscal_year)
- HOLDS_STAKE (person/company → company; pct, pledged_pct, promoter_group, as_of)
- SUBSIDIARY_OF (company → company; pct)
- AUDITED_BY (company → audit firm; fiscal_year)
- PARTY_TO (company/person → related-party transaction; side) — transactions have nature, amount_inr, fiscal_year
- NAMED_IN (company/person → regulatory action; order_date, action_type)
- IN_SECTOR (company → sector)

Return JSON:
{
  "mentions": [{"text": "...", "kind": "company|person|audit_firm|sector|unknown"}],
  "relation_types": ["DIRECTOR_OF", ...],
  "fiscal_years": ["FY2023-24", ...],   // only if stated or clearly implied
  "is_global": true|false               // true if about the whole dataset, not specific entities
}
Do not answer the question.

Question: {question}
```

Why include `fiscal_years`: time filters cut the subgraph drastically and improve precision.

Fallback if the call fails: use all relation types, no year filter, and do entity lookup (Turso DB FTS5) on capitalized phrases in the question.

### Step 2 — Linking (`linking.py`)

For each mention:
1. Build an FTS5 query from the mention: quote the phrase (escaping quotes), and also try the tokens joined with AND for multi-token names. Fuzziness comes from the RapidFuzz re-rank, not from the index.
2. `entity_search(query, kind, limit=5)` (Phase 3 queries: Turso DB FTS5 over `entities`, then RapidFuzz re-rank).
3. Choose the top candidate if:
    - Its re-rank score is clearly higher than the second (e.g. gap ≥ 5 points), **and**
    - `fuzz.token_set_ratio(norm(mention), norm(candidate.name or alias)) ≥ 85`.
4. Otherwise, if two candidates are close, keep both (max 2) and let expansion + the answer model disambiguate; record `ambiguous` in the trace.
5. No acceptable candidate → `unlinked` in the trace.

Output: `LinkedEntity(mention, entity_id, name, kind, score, status)` list.

Sector mentions: match against the small list of `Sector` names directly.

### Step 3 — Relation types (`relations.py`)

Merge the LLM's relation types with keyword rules (robust when the helper call is weak):

| Keywords in question | Add relation types |
| --- | --- |
| director, board, independent, appointed, resigned | DIRECTOR_OF |
| auditor, audited, audit firm | AUDITED_BY |
| related party, transaction, loan, sale to, purchase from | PARTY_TO |
| stake, shareholding, promoter, pledge | HOLDS_STAKE |
| subsidiary, group company | SUBSIDIARY_OF |
| order, penalty, regulator, debarred | NAMED_IN |
| sector, industry | IN_SECTOR |

If the result is empty, use all types.

### Step 4 — Expansion (`expand.py`)

Expansion is one call to the installed GSQL query `entity_neighbors` (Phase 3, Step 7), so the traversal, filtering and fan-out caps run inside TigerGraph.

Hop 1: all allowed edge types from each linked vertex.

```gsql
CREATE QUERY expand_hop(SET<VERTEX> seeds, SET<STRING> edge_types, SET<STRING> fys,
                        INT fanout = 50) FOR GRAPH Interlock SYNTAX v2 {
  // For each seed, walk edges whose type is in edge_types and whose fiscal_year is in fys
  // (or has none), keep at most `fanout` per seed (newest fiscal_year first), and PRINT
  // rows: src, edge_type, edge attributes (incl. edge_id, doc_id, page, quote),
  // start_id, end_id, neighbor type, neighbor id, neighbor name/nature/summary.
  // Edge-type filtering by a runtime set is written as one SELECT per type, or with
  // e.type IN edge_types (Verify support in your version). Per-seed caps use a
  // HeapAccum or per-vertex counter accumulator.
}
```

Notes:
- `RelatedPartyTxn` and `RegulatoryAction` vertices have `txn_id`/`order_id` as their primary id. Every GSQL vertex exposes its id uniformly (`v.id`, **Verify**), so use that and the vertex type name (`v.type`) instead of `coalesce(...)`.
- When the hop reaches a `RelatedPartyTxn`, automatically include the transaction's **other** `PARTY_TO` edge (the counterparty; traverse `HAS_PARTY` from the transaction). Otherwise a transaction vertex without its counterparty is useless. Treat "company → txn → counterparty" as one logical hop.

Hop 2: repeat from the hop-1 neighbor set (`hops=2` in `entity_neighbors`, which reuses the accumulators from hop 1), with:
- The same relation types, **excluding** `IN_SECTOR` and `AUDITED_BY` unless those types were explicitly requested (they are hubs).
- A smaller fan-out.
- Skip neighbors that are hubs: vertices with degree above a threshold (e.g. top 1% by degree). GSQL can read the degree of a vertex directly (`v.outdegree()`, **Verify**); compute the threshold once after the build, store it in config/run metadata, and pass it as a query parameter.

Parameters (start values, tune on dev):

| Param | Start |
| --- | --- |
| `max_hops` | 2 |
| `fanout_hop1` | 50 |
| `fanout_hop2` | 15 |
| `max_triples` | 150 |
| `hub_degree_threshold` | 99th percentile of degree |

### Step 5 — Triple ranking and caps (`rank.py`)

Score each triple:

```
score = 3.0 * touches_linked_entity
      + 2.0 * relation_requested
      + 1.5 * fiscal_year_matches
      + 1.0 * (hop == 1)
      + 1.0 * endpoint_mentioned_in_question
      + 0.5 * endpoint_in_dataset
```

Sort descending; deduplicate (same edge_id); keep `max_triples`. Also keep a per-relation-type minimum (e.g. at least 5 of each requested type if available) so one abundant type can't crowd out another.

### Step 6 — Serialization (`serialize.py`)

One evidence item per triple (or per transaction group):

```
Person: Anil Kumar Sharma —[DIRECTOR_OF: Independent Director; FY2023-24]→ Company: Example Industries Ltd
  source: doc 3f2a1c…, p.46 | quote: "Mr. Anil Kumar Sharma | Independent Director | 01234567"

Company: Example Industries Ltd —[RELATED-PARTY TXN FY2022-23: Sale of goods; ₹ 48.20 crore]→ Company: Example Trading Pvt Ltd (relationship: Entity controlled by promoter)
  source: doc 91bc07…, p.212 | quote: "Example Trading Private Limited | Sale of goods | 48.20"
```

Rules:
- Use names, not IDs (IDs stay in `EvidenceItem.ref_id` for scoring and UI).
- Always show time and value properties.
- Amounts: show normalized crore/lakh consistently plus the raw string if helpful.
- Group multiple triples sharing a source page into one evidence item if it saves tokens (optional).

Each item: `EvidenceItem(kind="triple", ref_id=edge_id, text=...)` and label map entry with `doc_id`, `page`.

### Step 7 — Linked text (`linked_text.py`)

1. Entities = linked entities + hop-1 neighbors.
2. `chunks_for_entities(ids, limit=50)`.
3. Rank by cosine similarity to the question embedding (compute on the fly from stored embeddings, or run the vector search and intersect).
4. Apply the reranker if enabled (same as RAG).
5. Keep top `linked_chunks` (e.g. 6).

### Step 8 — Budget split

Evidence budget is the same total as RAG (`evidence_token_budget`). Split, for example:
- Triples first, up to 60% of budget.
- Linked chunks fill the rest.
- If triples use less, chunks get the remainder.

Record the actual split in the trace. Tune the ratio on dev.

### Step 9 — Pipeline (`pipeline.py`)

```python
class GraphRAGPipeline:
    name = "graphrag"

    def answer(self, question: str, request_id: str) -> AnswerResult:
        tr = Tracer(self.ctx.store, request_id, self.name)
        start = time.perf_counter()
        try:
            plan = self.link_call(question, tr)                  # Step 1 (llm)
            if plan.is_global and self.ctx.cfg.graphrag_global_enabled:
                return self.global_answer(question, plan, tr, start)
            linked = link_entities(self.ctx, plan.mentions, tr)   # Step 2 (retrieve)
            types = choose_relations(question, plan, tr)          # Step 3
            triples = expand(self.ctx, linked, types, plan.fiscal_years, tr)   # Step 4
            triples = rank_and_cap(triples, linked, types, plan, question)    # Step 5
            t_items = serialize(triples)                           # Step 6
            c_items = linked_text(self.ctx, question, linked, triples, tr)    # Step 7
            items, labels = budget_split(t_items, c_items, self.ctx.cfg)      # Step 8
            ma, err = final_answer(self.ctx, tr, question, items, labels, self.name)
            ...  # identical post-processing to RAG: citations, status, AnswerResult
        except Exception as e:
            return error_result(self.name, question, tr, repr(e), start)
```

If no entity is linked and the question is not global: fall back to RAG-style vector search for evidence (so GraphRAG isn't artificially worse than RAG), and record `fallback=vector` in the trace. Document this design choice — it is fair because it uses the same shared retrieval function.

Store triples' `edge_id`s in `evidence` so the dashboard can highlight the subgraph.

### Step 10 — Global questions without community summaries (default)

Letting an LLM choose aggregation queries at question time would make GraphRAG agentic, blurring the comparison. Keep it single-pass and simple:
- For `is_global=true`, retrieve a precomputed **dataset statistics** evidence pack: per-sector counts (companies, auditor changes per year, regulatory actions, total RPT), top-N persons by board seats, etc. Precompute these once after the graph build (`graph/stats.py`, using GSQL accumulator queries) as evidence items with provenance "computed from graph at build <run_id>".
- This is transparent and honest; report it in the README as GraphRAG's global strategy.

### Step 11 — Optional: community summaries (`global_mode.py`)

Only after everything else works (secondary goal SG-2):
1. Build a projection of Company/Person vertices with DIRECTOR_OF, HOLDS_STAKE, SUBSIDIARY_OF, PARTY_TO links.
2. Run community detection (Louvain or Label Propagation) with **TigerGraph's graph algorithm library** (install it from TigerGraph's GDS/graph-algorithms repository and run it on this graph; **Verify** availability, edition and query names). Fallback: export the projection and use a Python library (networkx Louvain; igraph + leidenalg for Leiden).
3. For each community: collect its facts (capped), ask the helper LLM for a neutral summary with citations to edge IDs; store as `Community` vertices (schema change: add the vertex type, a `HAS_MEMBER` edge, and a vector attribute for the summary embedding) with `summary`.
4. Global questions: vector-search community summaries; answer from the top ones.
5. Evaluate on the global category; keep only if it beats the statistics pack.

### Step 12 — Tune on dev, then test

1. `hl eval --pipeline graphrag --split dev`.
2. Inspect failures by label. Typical fixes:
    - `entity_link_error` → aliases, fuzzy thresholds, mention prompt.
    - `missed_hop` → hop-2 fan-out, per-type minimums.
    - `retrieval_miss` with hubs → hub exclusion rules.
    - `temporal_error` → year filters.
3. Record parameter changes and their dev effect in ADR-0012.
4. `hl eval --pipeline graphrag --split test` once.
5. Compare with RAG per category using `paired_diff_ci`.

---

## 6.5 Tests

| Test | Expectation |
| --- | --- |
| FTS escaping | Names with quotes and special characters don't break entity lookup |
| Linking decision | Clear winner linked; close scores → up to 2 kept + `ambiguous`; low scores → `unlinked` |
| Relation keyword rules | "pledged shares" adds HOLDS_STAKE |
| Expansion caps | Never more than `max_triples`; fan-out respected; hubs skipped at hop 2 |
| Transaction completion | Reaching a txn includes its counterparty edge |
| Serialization | Every triple line includes source doc and page; names not IDs |
| Budget split | Total ≤ budget; unused triple budget passed to chunks |
| Fallback | No links + not global → vector evidence used; trace shows fallback |
| Integration (fixture graph, cached) | Known multi-hop question answered correctly; valid `AnswerResult` |

---

## 6.6 Error handling

| Situation | Behavior |
| --- | --- |
| Helper call fails | Keyword/capitalization fallback; trace notes it |
| TigerGraph timeout on expansion | Retry once with smaller fan-out; then fallback to vector evidence |
| Empty subgraph | Fallback to vector evidence |
| Invalid answer JSON | Same repair-once logic as RAG |

---

## 6.7 Exit criteria

| # | Criterion | How to check |
| --- | --- | --- |
| 1 | GraphRAG dev and test runs stored | `runs` |
| 2 | Beats RAG on multi-hop with a paired-difference CI above 0 — or a trace-based explanation of why not | Stats + ADR-0012 |
| 3 | Entity-link errors quantified | Failure labels |
| 4 | Parameters and fallback behavior documented | ADR-0012 |
| 5 | Tests pass | `make test` |

---

## 6.8 Pitfalls

| Symptom | Cause | Fix |
| --- | --- | --- |
| Context full of the same audit firm | Hub expansion | Hub exclusion at hop 2 |
| Right entities, wrong year | No year filter | Pass fiscal years from the link call |
| Transaction without counterparty | Hop stopped at the txn node | Transaction completion rule |
| GraphRAG worse than RAG on single-fact | Triples crowd out text that has the answer | Raise chunk share of the budget |
| Great dev results, worse test | Tuned too closely to dev templates | Hold-out templates; fewer, simpler rules |

---

## 6.9 Hand-off to Phase 7

The agent reuses: linking (`find_entity`), expansion (`neighbors`), linked text (`search_text` with filters), serialization for tool outputs, and the shared final answer.
