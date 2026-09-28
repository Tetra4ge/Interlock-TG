# Phase 3 — Full Extraction, Entity Resolution, TigerGraph Build and Embeddings

> **Accuracy note.** GSQL and `pyTigerGraph` calls are sketches written from general knowledge of TigerGraph. Verify schema-change, discriminator, vector-attribute and loading syntax against the documentation for the exact TigerGraph version you deployed (Phase 0, ADR-0011). Code blocks are sketches.

---

## 3.1 Overview

| Item | Detail |
| --- | --- |
| Goal | Run extraction on all companies; resolve every mention to a canonical entity; load a knowledge graph with provenance into TigerGraph; embed and index all chunks; install the GSQL queries the pipelines will use; link chunks to entities; rebuild everything with one command |
| Why | Without entity resolution, the same person appears as several nodes and multi-hop questions break. The TigerGraph graph + vector search is what all three pipelines query |
| Prerequisites | Phase 2 exit criteria met |
| Produces | `resolve/`, `graph/` (GSQL schema, loader, installed queries, Python wrappers), `embed/` packages; populated TigerGraph; `entities`, `merge_log` tables; `docs/data-quality.md`; ADR-0009 (embedding choice); committed sample graph export |
| PRD links | FR-15 to FR-20, NFR-01, NFR-02, NFR-09 |
| TRD links | §5 (`entities`, `merge_log`), §6 (graph schema), §3.3 `resolve` |

---

## 3.2 Concepts you will learn

### Entity resolution (ER)
Deciding which mentions refer to the same real-world thing. Standard steps:
1. **Normalization** — make comparable strings ("Mr. A. K. Sharma" → "a k sharma").
2. **Blocking** — only compare candidates likely to match (same surname, same company), so you avoid comparing every pair.
3. **Matching** — exact IDs first; similarity scores second.
4. **Clustering** — group matched mentions into entities.
5. **Human review** — for uncertain scores.

Errors come in two kinds:
- **False merge** (two people become one): creates fake links. Very harmful here.
- **False split** (one person becomes two): hides real links. Less harmful.
So auto-merge thresholds are set high and uncertain cases go to review.

### Graph modeling choices
- A **node** is a thing you want to query from or aggregate (a company, a transaction).
- A **relationship property** is a fact about how two things connect (role, period, percentage).
- Related-party transactions are nodes because they connect two parties *and* carry amount, nature and year you will filter and sum.

### Upsert semantics in TigerGraph
There is no `MERGE`. Loading a vertex with an existing `PRIMARY_ID` **updates** it, and loading an edge with the same source, target, type and discriminator value **updates** that edge (`upsert`). Reruns therefore never create duplicates, provided ids are deterministic. Edge types that must hold several parallel edges between the same two vertices declare a `DISCRIMINATOR` (here `edge_id`). Vertex and edge types cannot change freely after data exists: changing the schema needs a **schema-change job**, so freeze the schema early (Phase 0 spike, TRD §6).

### GSQL installed queries and accumulators
GSQL is TigerGraph's query language. A query is written once, **installed** (compiled), then called with typed parameters over REST. Traversals are written as `SELECT ... FROM ... ACCUM ...` blocks and collect results in **accumulators** (`SumAccum`, `SetAccum`, `ListAccum`, `HeapAccum`...), so multi-hop expansion and totals run inside the database, in parallel. Parameterized installed queries are also the safe interface for the agent (no string-built queries).

### Vector attributes and search
A vector attribute stores an embedding on a vertex; a vector search returns the vertices whose embeddings are most similar to a query vector (approximate nearest neighbour, cosine here). Support depends on the TigerGraph version (**Verify**, ADR-0011). Fallback if unsupported: local FAISS/NumPy index keyed by `chunk_id`; everything else stays in TigerGraph.

### Entity-name search (no graph full-text index)
TigerGraph has no built-in full-text index (**Verify**). Name → entity lookup is done over the `entities` table in Turso DB with an FTS5 index on `name` and `aliases`, then RapidFuzz re-ranking. Entities are few (thousands), so this is fast and simple.

---

## 3.3 Files created

```
src/interlock/resolve/
├── __init__.py
├── normalize.py      # person/company/firm name normalization
├── mentions.py       # build mention list from records
├── match.py          # blocking + exact + fuzzy matching
├── cluster.py        # union-find to form entities
└── review.py         # uncertain pairs → review
src/interlock/graph/
├── gsql/
│   ├── schema.gsql       # vertex/edge types, graph, vector attribute (TRD §6.3)
│   └── queries/*.gsql    # entity_neighbors, shared_directors, path_between, stake_aggregate, chunks_for_entities, vector_chunks, delete_run
├── schema.py         # apply schema and (re)install queries
├── loader.py         # vertices, edges, provenance (batched upserts)
├── mentions_link.py  # Chunk-[:MENTIONS]->entity
├── export.py         # JSONL export/import for the sample graph
└── queries.py        # Python wrappers over installed queries, used by pipelines
src/interlock/embed/
├── __init__.py
├── provider.py       # local or hosted embedding provider
├── index.py          # write embeddings to TigerGraph (or the local fallback index)
└── recall_test.py    # choose the model
tests/unit/test_normalize.py, test_match.py, test_cluster.py, test_entity_fts.py
tests/integration/test_loader_idempotent.py, test_graph_queries.py
docs/data-quality.md
docs/decisions/0009-embedding-model.md
data/samples/graph/*.jsonl
```

---

## 3.4 Step-by-step implementation

### Step 1 — Run extraction on all companies

1. Run parse → sections → chunk → extract for every registered document using the Phase 2 prompts and rules (same versions).
2. The run is resumable: documents with `status='extracted'` are skipped; cached LLM calls are free.
3. Watch the spend counter. If the cap triggers, raise it deliberately (with a note) or reduce scope.
4. Process the review queue in batches. Prioritize reasons `unit_unknown` and `holding_sum` (they affect numeric questions).
5. Spot-check 5 random new documents against the PDF to make sure nothing regressed at scale.

### Step 2 — Build mentions (`resolve/mentions.py`)

A **mention** is one occurrence of a name in one accepted record.

```python
class Mention(BaseModel):
    mention_id: str          # f"{record_id}:{role}"  e.g. "r123:person", "r123:company"
    kind: str                # person | company | audit_firm
    raw_name: str
    norm_name: str
    ids: dict                # {"din": "..."} | {"cin": "..."} | {"frn": "..."}
    context_company_id: str | None   # the reporting company, for blocking
    record_id: str
```

Examples:
- A `DirectorRecord` gives a person mention (with DIN if present) and a company mention (the reporting company; its ID is already known from config).
- A `RelatedPartyTxnRecord` gives a company mention for the reporting company and a mention for the counterparty (person **or** company — decide kind with a simple rule: company suffixes like "Limited", "Pvt", "LLP", "Trust", "Private" → company; otherwise person; ambiguous → company and flag).
- A `RegulatoryActionRecord` gives one mention per named entity.

### Step 3 — Normalization (`resolve/normalize.py`)

```python
import re
from interlock.parse.clean import normalize_for_match

HONORIFICS = r"\b(mr|mrs|ms|miss|dr|shri|smt|sri|kum|prof|capt|col|justice|ca|cs)\b\.?"
COMPANY_SUFFIX = r"\b(limited|ltd|private|pvt|llp|inc|incorporated|co|company|corporation|corp)\b\.?"

def norm_person(name: str) -> str:
    s = normalize_for_match(name)
    s = re.sub(HONORIFICS, " ", s)
    s = re.sub(r"[^a-z\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def norm_company(name: str) -> str:
    s = normalize_for_match(name)
    s = s.replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s)             # remove bracketed former names
    s = re.sub(COMPANY_SUFFIX, " ", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def surname_key(norm: str) -> str:
    parts = norm.split()
    return parts[-1] if parts else ""

def initials_signature(norm: str) -> str:
    # "a k sharma" and "anil kumar sharma" → "aks"
    return "".join(p[0] for p in norm.split())
```

Indian naming note: surname position varies, and many names are written with initials first ("A. K. Sharma") or surname first in some registers. Blocking on the last token catches the common case; also block on the first token when the last token is a single letter.

### Step 4 — Matching (`resolve/match.py`)

Order of decisions for each mention:

| Priority | Rule | Method label | Confidence |
| --- | --- | --- | --- |
| 1 | Person with DIN → entity `P:<din>` | `din` | Certain |
| 2 | Company in `companies.yaml` (by config id) or with CIN → `C:<cin or company_id>` | `cin` / `config` | Certain |
| 3 | Audit firm with registration number → `A:<frn>` | `frn` | Certain |
| 4 | Exact normalized name match to an existing entity within the same block | `exact_name` | High |
| 5 | Fuzzy match within block, score ≥ `auto_merge_threshold` (e.g. 95) **and** compatible initials | `fuzzy` | Medium-high |
| 6 | Fuzzy score in [`review_band_low`, threshold) | → review queue | Uncertain |
| 7 | Otherwise new entity with hashed id `P:x<hash>` / `C:x<hash>` / `A:x<hash>` | `new` | — |

Blocking keys:
- **Persons:** (surname key) and, for directors, also the context company. A person without DIN mentioned in a related-party note of company X is compared against directors of company X first — that is where the true match usually is.
- **Companies:** first 2 tokens of the normalized name.
- **Audit firms:** first token.

Fuzzy scoring (RapidFuzz; **Verify** function names):

```python
from rapidfuzz import fuzz

def person_score(a: str, b: str) -> float:
    base = fuzz.token_sort_ratio(a, b)
    if initials_signature(a) != initials_signature(b):
        # "a sharma" vs "r sharma" must never merge
        if not (set(initials_signature(a)) <= set(initials_signature(b)) or
                set(initials_signature(b)) <= set(initials_signature(a))):
            return 0.0
    return base

def company_score(a: str, b: str) -> float:
    return fuzz.token_set_ratio(a, b)
```

Special rule: never fuzzy-merge two mentions that both have **different** official IDs (two different DINs are two people, whatever their names).

### Step 5 — Clustering (`resolve/cluster.py`)

Use union-find (disjoint set) over mention IDs:

```python
class UnionFind:
    def __init__(self): self.parent = {}
    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x
    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb: self.parent[rb] = ra
```

After unions, each cluster becomes one entity:
- `entity_id`: the official-ID form if any member has one (`P:<din>`), else a stable hash of the sorted normalized names.
- `canonical_name`: the most frequent raw name in the cluster (ties → longest).
- `aliases`: all distinct raw names.

**Conflict check:** if a cluster contains two different DINs, split it and send to review — this indicates a bad fuzzy merge.

Write to `entities` and one `merge_log` row per mention (`method`, `score`, `reason`).

### Step 6 — Resolution quality check

1. Randomly sample 50 merges (mentions resolved to an entity with ≥2 mentions via `exact_name`/`fuzzy`) and 50 non-merges (pairs in the same block that were *not* merged, scored 80–95).
2. Label each by looking at the source pages.
3. Report precision of merges and the rate of missed merges in `docs/data-quality.md`.
4. If merge precision is below ~98%, raise the threshold; false merges are the expensive error.

### Step 7 — Graph schema and queries (`graph/schema.py`, `graph/gsql/`)

1. Apply `schema.gsql` (TRD §6.3) through `conn.gsql(...)`. Make it rerunnable: check `conn.getVertexTypes()` first and skip if the graph already exists; use schema-change jobs for later changes.
2. Add the vector attribute **after** Step 11 (when you know the embedding dimension), if the version supports it.
3. Write each installed query as a `.gsql` file and install it (`INSTALL QUERY <name>`, or `INSTALL QUERY ALL`). Installation compiles C++ and can take minutes; do it once per query change, not on every run. Keep a `queries.lock` (hash of each file) and reinstall only what changed.
4. Smoke-call each query with a tiny fixture graph.

Query sketches (**Verify** syntax):

```gsql
CREATE QUERY entity_neighbors(SET<VERTEX> seeds, INT hops = 1, STRING fiscal_year = "",
                              INT max_triples = 150) FOR GRAPH Interlock SYNTAX v2 {
  ListAccum<STRING> @@triples;   // real version returns structured edge rows with provenance
  SetAccum<VERTEX> @@frontier;
  Start = seeds;
  // hop 1
  Hop1 = SELECT t FROM Start:s -(:e)- :t
         WHERE fiscal_year == "" OR e.fiscal_year == fiscal_year   // edge types without the attribute need per-type handling; Verify
         ACCUM @@triples += s.entity_id + "|" + e.type + "|" + t.entity_id
         LIMIT max_triples;
  // hop 2 repeats the pattern from Hop1 when hops == 2
  PRINT @@triples;
}
```

```gsql
CREATE QUERY stake_aggregate(VERTEX<Company> company) FOR GRAPH Interlock SYNTAX v2 {
  SumAccum<DOUBLE> @@pledged;
  S = {company};
  R = SELECT h FROM S:c -(HELD_BY:e)- :h ACCUM @@pledged += e.pledged_pct;
  PRINT @@pledged;
}
```

### Step 8 — Loader (`graph/loader.py`)

Principles:
- **Batch** rows (e.g. 500 to 1000 per request) with `conn.upsertVertices(vertex_type, [(id, {attrs}), ...])` and `conn.upsertEdges(src_type, edge_type, tgt_type, [(src_id, tgt_id, {attrs}), ...])` (**Verify** signatures). For very large loads a GSQL `LOADING JOB` fed with CSV/JSONL through `runLoadingJobWithData` is an alternative.
- **Deterministic IDs**: `edge_id = sha256(record_id + rel_type)[:16]`, `txn_id = sha256(record_id)[:16]`. Include `edge_id` in the edge attributes (it is the discriminator).
- **Provenance on every fact edge**: `doc_id, page, quote, run_id, edge_id`.
- **Order**: vertices first (Sector, Document, AuditFirm, Person, Company, RegulatoryAction, RelatedPartyTxn), then edges. Upserting an edge whose endpoint does not exist may create an empty endpoint vertex or fail depending on configuration (**Verify**); loading vertices first avoids it.
- Load failures: `pyTigerGraph` returns accepted counts; compare with rows sent and raise on mismatch.

Vertices (`Company` example):

```python
rows = [(e.entity_id, {"name": e.name, "cin": e.cin, "aliases_text": e.aliases_text,
                       "sector": e.sector, "in_dataset": e.in_dataset}) for e in batch]
conn.upsertVertices("Company", rows)
```

(`in_dataset=true` for companies from `companies.yaml`; counterparties outside the dataset are still `Company` vertices but flagged, which matters for questions like "companies in the dataset".) Same pattern for `Person`, `AuditFirm`, `Sector`, `Document`, `RegulatoryAction`.

Sector links:

```python
conn.upsertEdges("Company", "IN_SECTOR", "Sector", [(c.entity_id, c.sector, {}) for c in batch])
```

Directors:

```python
conn.upsertEdges("Person", "DIRECTOR_OF", "Company", [
    (r.person_id, r.company_id, {
        "edge_id": r.edge_id, "role": r.role, "independent": r.independent,
        "start_date": r.start_date, "end_date": r.end_date, "fiscal_year": r.fiscal_year,
        "doc_id": r.doc_id, "page": r.page, "quote": r.quote, "run_id": r.run_id})
    for r in batch])
```

Note on directors across years: each fiscal year's report produces its own `DIRECTOR_OF` edge (different `edge_id` discriminator). That is intentional: it records "was a director according to the FY2022-23 report". Questions about periods then filter on `fiscal_year` or on `start_date`/`end_date` where available. Document this choice in the README.

Related-party transactions: upsert the `RelatedPartyTxn` vertex (with `amount_inr`, `nature`, `relationship`, `fiscal_year`), then two `PARTY_TO` edges, one with `side = "reporting"` from the reporting `Company`, one with `side = "counterparty"` from the counterparty (`Company` or `Person`, chosen by its resolved kind).

Write similar loaders for `HOLDS_STAKE`, `SUBSIDIARY_OF`, `AUDITED_BY`, `NAMED_IN`, `HAS_CHUNK`.

Deleting a bad run: an installed query `delete_run(STRING run_id)` that selects edges/vertices with that `run_id` and uses GSQL `DELETE` (**Verify** edge-delete syntax), or `conn.delEdges` / `conn.delVertices` from a list gathered by a read query.

### Step 9 — Chunks into the graph

```python
conn.upsertVertices("Chunk", [(c.chunk_id, {
    "text": c.text, "section": c.section, "page_start": c.page_start,
    "page_end": c.page_end, "fiscal_year": c.fiscal_year, "company_id": c.company_id})
    for c in batch])
conn.upsertEdges("Document", "HAS_CHUNK", "Chunk", [(c.doc_id, c.chunk_id, {}) for c in batch])
```

### Step 10 — MENTIONS links (`graph/mentions_link.py`)

A chunk mentions an entity if:
1. A record extracted from pages overlapping the chunk resolved to that entity (precise), **or**
2. The chunk text contains the entity's canonical name or an alias with ≥ 2 tokens (string match after normalization). Single-token aliases are skipped to avoid false links (e.g. a surname alone).

```python
conn.upsertEdges("Chunk", "MENTIONS", "Company", [(chunk_id, entity_id, {}) ...])
# repeat for Person and AuditFirm, choosing the target type from the entity kind
```

Report the number of chunks with at least one MENTIONS link; GraphRAG depends on it.

### Step 11 — Embedding model choice (`embed/recall_test.py`)

1. Write 30 questions by hand, each with the chunk IDs that contain the answer (look them up in GraphStudio or the chunk files). Cover all sections.
2. For each candidate model (e.g. one hosted embedding model and one open-weight model via sentence-transformers — **Verify** model names and dimensions on the model card):
    - Embed all chunks (cache by `chunk_id + model`).
    - Embed each question; compute cosine similarity; take top 10.
    - Recall@10 = share of questions where at least one gold chunk is in the top 10.
3. Also record: embedding time for the corpus, cost (hosted), vector dimension.
4. Pick the best trade-off; write `docs/decisions/0009-embedding-model.md`.

Many embedding models expect a query prefix or instruction for queries vs passages (e.g. "query: " / "passage: "). **Verify** on the model card; getting this wrong can lower recall noticeably.

Local sketch:

```python
from sentence_transformers import SentenceTransformer
model = SentenceTransformer(model_name)                    # Verify
vecs = model.encode(texts, batch_size=32, normalize_embeddings=True)  # Verify args
```

### Step 12 — Write embeddings and enable vector search (`embed/index.py`)

1. Add the vector attribute with the model's dimension (schema-change job from TRD §6.3): `ALTER VERTEX Chunk ADD VECTOR ATTRIBUTE embedding(DIMENSION=<dim>, METRIC="COSINE")`. **Verify** syntax and supported index types for your version.
2. Upsert the embeddings in batches. Depending on the version this is done through a loading job that maps a vector column, or a REST upsert that accepts the vector (**Verify**). Cache vectors on disk by `chunk_id + model` so a rebuild never re-embeds.
3. Wait until the vector index is built (**Verify** how to check status), then run the smoke test.

Smoke test (**Verify** function name and signature for your version):

```gsql
CREATE QUERY vector_chunks(LIST<FLOAT> qvec, INT k = 10) FOR GRAPH Interlock SYNTAX v2 {
  // native vector search over Chunk.embedding, e.g. vectorSearch({Chunk.embedding}, qvec, k)
  // returns the top-k Chunk vertices; PRINT their chunk_id, page_start, score
}
```

**Fallback (if native vectors are not available in your TigerGraph version):** keep embeddings in a local index (FAISS or a NumPy matrix) saved to `data/vectors/`, keyed by `chunk_id`. `vector_search` then returns chunk ids from the local index and reads chunk text and links from TigerGraph. Record which mode is used in ADR-0011, and expose it in the `/health` response and dashboard so the comparison stays honest.

### Step 13 — Shared read queries (`graph/queries.py`)

Write and test these now; Phases 4–7 reuse them. Each graph function calls an **installed GSQL query** through `run_installed`.

| Function | Purpose | Sketch |
| --- | --- | --- |
| `vector_search(qvec, k, filters)` | Top-k chunks, optional company/year/section filter | `vector_chunks` query (or local index); over-fetch k×3 then filter |
| `entity_search(text, kind, limit)` | Name → entity candidates | Turso DB FTS5 query on `entities` (escape FTS syntax characters in user text, use quoted phrases), then RapidFuzz re-rank |
| `neighbors(entity_id, rel_types, hops, fy)` | Bounded expansion | `entity_neighbors` query |
| `shared_directors(ids, fy)` | Common directors between companies | `shared_directors` query |
| `path_between(a, b, max_hops)` | Bounded shortest path | `path_between` query |
| `aggregate_stake(entity_id)` / `sum_txn(...)` | Totals over a subgraph | `stake_aggregate` and related accumulator queries |
| `chunks_for_entities(ids, limit)` | Linked text | `chunks_for_entities` query |
| `get_edge(edge_id)` | Provenance for citations | edge lookup via `conn.getEdges(...)` or a small installed query (**Verify**) |
| `get_chunk(chunk_id)` | Chunk text + pages | `conn.getVerticesById("Chunk", chunk_id)` |

Sanity checks to run in GraphStudio (or via `conn`) after loading:

- Vertex counts by type: `conn.getVertexCount("*")` (**Verify**).
- Edge counts by type: `conn.getEdgeCount("*")` (**Verify**).
- Directors shared between dataset companies: call `shared_directors` on a few dataset company ids and eyeball the results.
- Fact edges missing provenance (should be 0): a small installed query `edges_missing_provenance` that scans each fact edge type and counts edges with empty `doc_id` or `page = 0`.

### Step 14 — One-command build

`hl build-graph` runs, in order, skipping completed work:

1. `migrate` (Turso DB) and `schema` (TigerGraph schema and installed queries, skipped if unchanged)
2. `parse` all registered documents
3. `sections` + `chunk`
4. `extract` (resumable, cached)
5. `resolve`
6. `load` nodes, edges, chunks
7. `mentions`
8. `embed` + vector attribute (or local vector index)
9. `entity-index`: rebuild the Turso DB FTS5 table from `entities`

Flags: `--from <step>` to restart from a step; `--reset-graph` to wipe the graph's data first (`CLEAR GRAPH STORE` in GSQL, or drop and recreate the graph; **Verify** the current command and that it only affects this graph). This is destructive: the command must print what it will delete and require `--yes`.

### Step 15 — Data quality report (`docs/data-quality.md`)

Generate automatically:

| Section | Numbers |
| --- | --- |
| Documents | registered / parsed / failed / probable scans |
| Records | extracted / accepted / rejected (by reason) / reviewed |
| Extraction quality | precision/recall per type from labeled pages |
| Entity resolution | entities by kind; mentions resolved by method; merge precision from sample |
| Graph | node counts by label; edge counts by type; % fact edges with provenance (must be 100%) |
| Coverage | % chunks with MENTIONS links; companies with 0 directors (investigate) |

### Step 16 — Sample graph export (`graph/export.py`)

For the judges' one-command demo, export a subset (e.g. 10–15 companies with interesting links, plus all their neighbors) to JSONL files:

- `vertices.jsonl`: `{vertex_type, id, attrs}`
- `edges.jsonl`: `{edge_type, src_type, src_id, tgt_type, tgt_id, attrs}`

Include chunk embeddings for those companies (this can be large; keep the sample small). An import script recreates the graph with the same `upsertVertices` / `upsertEdges` calls after applying the schema. This is simpler and more version-proof than database backup files; TigerGraph's own `gbar` backup/restore or export tools are an alternative (**Verify** edition support and procedure).

---

## 3.5 Tests

| Test | Expectation |
| --- | --- |
| `norm_person` | "Mr. A.K. Sharma" == "a k sharma"; "Smt. Priya Rao" == "priya rao" |
| `norm_company` | "XYZ Industries Ltd." == "XYZ Industries Limited" |
| `person_score` | "a k sharma" vs "anil kumar sharma" high; "a sharma" vs "r sharma" = 0 |
| Different DINs never merge | Two mentions with different DINs in separate entities |
| Union-find | Transitive merges form one cluster |
| Cluster conflict split | Cluster with two DINs is split and queued |
| Loader idempotency | Load twice → identical node/edge counts |
| Provenance completeness | Query returns 0 fact edges missing doc/page |
| Graph queries on fixture graph | Known 2-hop answer returned; `neighbors` respects hop and type filters |
| FTS escaping | Names with `&`, `(`, `-`, quotes don't crash the Turso DB FTS5 query |

Fixture graph: 5 companies, 8 persons, 1 audit firm, 1 regulatory action, 4 transactions — small enough to reason about by hand.

---

## 3.6 Error handling

| Situation | Behavior |
| --- | --- |
| Counterparty kind unclear | Default to company; flag in merge_log reason |
| Cluster with conflicting IDs | Split; review |
| Loader batch failure | Transaction rolls back; retry batch; log failing row ids |
| Embedding provider failure | Retry with backoff; resumable by chunk_id |
| Vector index still building | Wait/poll the index status before smoke test (**Verify** how) |
| Installed query out of date | Reinstall changed `.gsql` files; the `queries.lock` hash check catches this |

---

## 3.7 Exit criteria

| # | Criterion | How to check |
| --- | --- | --- |
| 1 | `hl build-graph` rebuilds from raw files | Run on a clean TigerGraph graph |
| 2 | 100% of fact edges have provenance | Sanity query returns zero |
| 3 | Merge precision measured and ≥ your bar (suggested ~98%) | `docs/data-quality.md` |
| 4 | Embedding model chosen by recall test | ADR-0009 |
| 5 | Vector search (native or fallback) and entity FTS work; all installed queries return sane results | GraphStudio + smoke tests |
| 6 | Sample graph export + import works on an empty database | Integration test |
| 7 | Interesting multi-hop links exist (shared directors, directors named in orders, RPT counterparties with overlapping boards) | Sanity queries return results |

If item 7 returns almost nothing, the dataset cannot separate the pipelines. Fix before moving on: add companies connected by the links you found, or run the second regulatory-order search using resolved director names (see Phase 1 Step 8).

---

## 3.8 Pitfalls and debugging

| Symptom | Cause | Fix |
| --- | --- | --- |
| One "person" connected to dozens of unrelated companies | False merge on a common name | Raise threshold; require initials compatibility; check clusters by degree |
| Same director appears as two nodes | DIN missing in one report | Add same-company blocking; review band |
| Loader very slow | One row per transaction | UNWIND batches |
| Duplicate relationships on rerun | Edge type missing a `DISCRIMINATOR`, or `edge_id` not deterministic | Add `DISCRIMINATOR(edge_id)` (schema change) and make ids deterministic |
| Vector search returns nothing | Dimension mismatch or index not built | Check the vector attribute's dimension against the model and the index status |
| FTS errors on some names | Unescaped FTS5 syntax characters | Quote the phrase and escape quotes before querying |
| Edge upsert silently creates empty vertices or drops edges | Endpoints not loaded yet, or wrong endpoint types on a multi-endpoint edge | Load vertices first; check edge definitions and accepted counts |
| Schema change fails with data loaded | Schema jobs may not allow some changes on populated graphs | Freeze schema early; for breaking changes drop the graph and rebuild (one-command build) |

---

## 3.9 Hand-off to Phase 4

Phase 4 needs: chunks with embeddings in vector search (TigerGraph native or fallback), `graph/queries.py` functions, and the sample graph for tests.
