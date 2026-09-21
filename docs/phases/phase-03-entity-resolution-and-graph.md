# Phase 3 — Full Extraction, Entity Resolution, Graph Build and Embeddings

> **Accuracy note.** Cypher shown uses Neo4j 5 syntax as I understand it; verify index/constraint and vector-query syntax for your exact version. Code blocks are sketches.

---

## 3.1 Overview

| Item | Detail |
| --- | --- |
| Goal | Run extraction on all companies; resolve every mention to a canonical entity; load a knowledge graph with provenance; embed and index all chunks; link chunks to entities; rebuild everything with one command |
| Why | Without entity resolution, the same person appears as several nodes and multi-hop questions break. The graph + vector index is what all three pipelines query |
| Prerequisites | Phase 2 exit criteria met |
| Produces | `resolve/`, `graph/` (schema, loader, queries), `embed/` packages; populated Neo4j; `entities`, `merge_log` tables; `docs/data-quality.md`; ADR-0009 (embedding choice); committed sample graph export |
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

### MERGE semantics
`MERGE (n:Company {entity_id: $id})` finds the node if it exists or creates it. With a uniqueness constraint, reruns never create duplicates. Use `ON CREATE SET` / `SET` to update properties. MERGE on a relationship matches the whole pattern, so include a stable key (`edge_id`) in the pattern to keep it idempotent.

### Vector indexes
An approximate nearest-neighbour (ANN) index returns the chunks whose embeddings are most similar to a query embedding, in milliseconds, without comparing against every vector. Similarity function here: cosine.

### Full-text indexes
A Lucene-based text index over entity names and aliases. Used by GraphRAG and the agent to go from a name in a question to a node, tolerating word order and partial matches.

---

## 3.3 Files created

```
src/hidden_links/resolve/
├── __init__.py
├── normalize.py      # person/company/firm name normalization
├── mentions.py       # build mention list from records
├── match.py          # blocking + exact + fuzzy matching
├── cluster.py        # union-find to form entities
└── review.py         # uncertain pairs → review
src/hidden_links/graph/
├── schema.py         # constraints and indexes
├── loader.py         # nodes, edges, provenance (batched)
├── mentions_link.py  # Chunk-[:MENTIONS]->entity
├── export.py         # JSONL export/import for the sample graph
└── queries.py        # shared read queries used later by pipelines
src/hidden_links/embed/
├── __init__.py
├── provider.py       # local or hosted embedding provider
├── index.py          # write embeddings to Neo4j
└── recall_test.py    # choose the model
tests/unit/test_normalize.py, test_match.py, test_cluster.py
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
from hidden_links.parse.clean import normalize_for_match

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

### Step 7 — Graph schema (`graph/schema.py`)

Run the constraints and indexes from TRD §6.3 at startup of `build-graph` (they use `IF NOT EXISTS`, so reruns are safe). Set the vector index `vector.dimensions` to your embedding model's dimension **after** Step 11 (create the vector index then).

### Step 8 — Loader (`graph/loader.py`)

Principles:
- **Batch** rows (e.g. 500 per transaction) using `UNWIND $rows AS row`.
- **Deterministic IDs**: `edge_id = sha256(record_id + rel_type)[:16]`, `txn_id = sha256(record_id)[:16]`.
- **Provenance on every fact edge**: `doc_id, page, quote, run_id, edge_id`.

Nodes:

```cypher
UNWIND $rows AS row
MERGE (c:Company {entity_id: row.entity_id})
SET c.name = row.name, c.cin = row.cin, c.aliases = row.aliases,
    c.aliases_text = row.aliases_text, c.sector = row.sector,
    c.in_dataset = row.in_dataset
```

(`in_dataset=true` for companies from `companies.yaml`; counterparties outside the dataset are still Company nodes but flagged, which matters for questions like "companies in the dataset".)

Same pattern for `Person`, `AuditFirm`, `Sector`, `Document`.

Sector links:

```cypher
UNWIND $rows AS row
MATCH (c:Company {entity_id: row.company_id})
MERGE (s:Sector {name: row.sector})
MERGE (c)-[:IN_SECTOR]->(s)
```

Directors:

```cypher
UNWIND $rows AS row
MATCH (p:Person {entity_id: row.person_id})
MATCH (c:Company {entity_id: row.company_id})
MERGE (p)-[r:DIRECTOR_OF {edge_id: row.edge_id}]->(c)
SET r.role = row.role, r.independent = row.independent,
    r.from = row.from, r.to = row.to, r.fiscal_year = row.fiscal_year,
    r.doc_id = row.doc_id, r.page = row.page, r.quote = row.quote, r.run_id = row.run_id
```

Note on directors across years: each fiscal year's report produces its own `DIRECTOR_OF` edge (different `edge_id`). That is intentional: it records "was a director according to the FY2022-23 report". Questions about periods then filter on `fiscal_year` or on `from`/`to` where available. Document this choice in the README.

Related-party transactions:

```cypher
UNWIND $rows AS row
MATCH (rep:Company {entity_id: row.reporting_id})
MATCH (cp {entity_id: row.counterparty_id})
MERGE (t:RelatedPartyTxn {txn_id: row.txn_id})
SET t.fiscal_year = row.fiscal_year, t.nature = row.nature,
    t.relationship = row.relationship, t.amount_inr = row.amount_inr,
    t.amount_raw = row.amount_raw,
    t.doc_id = row.doc_id, t.page = row.page, t.quote = row.quote, t.run_id = row.run_id
MERGE (rep)-[a:PARTY_TO {edge_id: row.edge_id_rep}]->(t) SET a.side = 'reporting'
MERGE (cp)-[b:PARTY_TO {edge_id: row.edge_id_cp}]->(t) SET b.side = 'counterparty'
```

Write similar statements for `HOLDS_STAKE`, `SUBSIDIARY_OF`, `AUDITED_BY`, `NAMED_IN` (with `RegulatoryAction` nodes), `HAS_CHUNK`.

Deleting a bad run:

```cypher
MATCH ()-[r {run_id: $run_id}]-() DELETE r;
MATCH (t:RelatedPartyTxn {run_id: $run_id}) DETACH DELETE t;
```

### Step 9 — Chunks into the graph

```cypher
UNWIND $rows AS row
MATCH (d:Document {doc_id: row.doc_id})
MERGE (ch:Chunk {chunk_id: row.chunk_id})
SET ch.text = row.text, ch.section = row.section, ch.page_start = row.page_start,
    ch.page_end = row.page_end, ch.fiscal_year = row.fiscal_year,
    ch.company_id = row.company_id
MERGE (d)-[:HAS_CHUNK]->(ch)
```

### Step 10 — MENTIONS links (`graph/mentions_link.py`)

A chunk mentions an entity if:
1. A record extracted from pages overlapping the chunk resolved to that entity (precise), **or**
2. The chunk text contains the entity's canonical name or an alias with ≥ 2 tokens (string match after normalization). Single-token aliases are skipped to avoid false links (e.g. a surname alone).

```cypher
UNWIND $rows AS row
MATCH (ch:Chunk {chunk_id: row.chunk_id})
MATCH (e {entity_id: row.entity_id})
MERGE (ch)-[:MENTIONS]->(e)
```

Report the number of chunks with at least one MENTIONS link; GraphRAG depends on it.

### Step 11 — Embedding model choice (`embed/recall_test.py`)

1. Write 30 questions by hand, each with the chunk IDs that contain the answer (look them up in Neo4j Browser or the chunk files). Cover all sections.
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

### Step 12 — Write embeddings and create the vector index (`embed/index.py`)

```cypher
UNWIND $rows AS row
MATCH (ch:Chunk {chunk_id: row.chunk_id})
SET ch.embedding = row.embedding
```

Neo4j may provide a dedicated procedure for setting vector properties with type checking (**Verify**, e.g. a `db.create.setNodeVectorProperty` procedure); plain `SET` of a list of floats is the simple approach.

Then create the vector index with the correct dimension (TRD §6.3) and wait for it to come online (check with `SHOW INDEXES`).

Smoke test query (**Verify** procedure name/signature for your version; newer versions may also offer a `SEARCH` clause):

```cypher
CALL db.index.vector.queryNodes('chunk_embedding', 10, $qvec)
YIELD node, score
RETURN node.chunk_id AS chunk_id, node.page_start AS page, score
```

### Step 13 — Shared read queries (`graph/queries.py`)

Write and test these now; Phases 4–7 reuse them.

| Function | Purpose | Sketch |
| --- | --- | --- |
| `vector_search(qvec, k, filters)` | Top-k chunks, optional company/year/section filter | vector procedure, then `WHERE` filters (over-fetch k×3 then filter) |
| `fulltext_entities(text, kind, limit)` | Name → entity candidates | `CALL db.index.fulltext.queryNodes('entity_names', $q) YIELD node, score` (**Verify**) |
| `neighbors(entity_id, rel_types, hops, fy)` | Bounded expansion | parameterized pattern per hop count |
| `chunks_for_entities(ids, limit)` | Linked text | `MATCH (c:Chunk)-[:MENTIONS]->(e) WHERE e.entity_id IN $ids` |
| `get_edge(edge_id)` | Provenance for citations | `MATCH ()-[r {edge_id:$id}]->() RETURN r` |
| `get_chunk(chunk_id)` | Chunk text + pages | simple match |

Full-text query strings use Lucene syntax; escape special characters (`+ - && || ! ( ) { } [ ] ^ " ~ * ? : \ /`) in user text before querying, then optionally append `~` to tokens for fuzzy matching.

Sanity queries to run in Neo4j Browser after loading:

```cypher
// counts by label
MATCH (n) RETURN labels(n)[0] AS label, count(*) ORDER BY label;

// directors shared between dataset companies
MATCH (c1:Company {in_dataset:true})<-[:DIRECTOR_OF]-(p:Person)-[:DIRECTOR_OF]->(c2:Company {in_dataset:true})
WHERE c1.entity_id < c2.entity_id
RETURN p.name, c1.name, c2.name LIMIT 25;

// fact edges missing provenance (should be 0)
MATCH ()-[r]->() WHERE type(r) IN ['DIRECTOR_OF','HOLDS_STAKE','SUBSIDIARY_OF','AUDITED_BY','PARTY_TO','NAMED_IN']
  AND (r.doc_id IS NULL OR r.page IS NULL)
RETURN type(r), count(*);
```

### Step 14 — One-command build

`hl build-graph` runs, in order, skipping completed work:

1. `migrate` (SQLite) and `schema` (Neo4j constraints/indexes)
2. `parse` all registered documents
3. `sections` + `chunk`
4. `extract` (resumable, cached)
5. `resolve`
6. `load` nodes, edges, chunks
7. `mentions`
8. `embed` + vector index

Flags: `--from <step>` to restart from a step; `--reset-graph` to wipe Neo4j first (`MATCH (n) DETACH DELETE n` in batches for large graphs; **Verify** the recommended batched-delete approach).

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

- `nodes.jsonl`: `{label, props}`
- `rels.jsonl`: `{type, start_label, start_key, end_label, end_key, props}`

Include chunk embeddings for those companies (this can be large; keep the sample small). An import script recreates the graph with the same MERGE statements. This is simpler and more version-proof than database dump files; Neo4j's own dump/load tools are an alternative (**Verify** Community Edition procedure and whether the database must be stopped).

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
| Full-text escaping | Names with `&`, `(`, `-` don't crash the query |

Fixture graph: 5 companies, 8 persons, 1 audit firm, 1 regulatory action, 4 transactions — small enough to reason about by hand.

---

## 3.6 Error handling

| Situation | Behavior |
| --- | --- |
| Counterparty kind unclear | Default to company; flag in merge_log reason |
| Cluster with conflicting IDs | Split; review |
| Loader batch failure | Transaction rolls back; retry batch; log failing row ids |
| Embedding provider failure | Retry with backoff; resumable by chunk_id |
| Vector index still populating | Wait/poll `SHOW INDEXES` before smoke test |

---

## 3.7 Exit criteria

| # | Criterion | How to check |
| --- | --- | --- |
| 1 | `hl build-graph` rebuilds from raw files | Run on a clean Neo4j |
| 2 | 100% of fact edges have provenance | Sanity query returns zero |
| 3 | Merge precision measured and ≥ your bar (suggested ~98%) | `docs/data-quality.md` |
| 4 | Embedding model chosen by recall test | ADR-0009 |
| 5 | Vector and full-text indexes online; smoke queries work | Neo4j Browser |
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
| Duplicate relationships on rerun | MERGE pattern without edge_id | Include edge_id in MERGE |
| Vector search returns nothing | Dimension mismatch or index not online | Check `SHOW INDEXES` and model dimension |
| Full-text errors on some names | Unescaped Lucene characters | Escape before querying |

---

## 3.9 Hand-off to Phase 4

Phase 4 needs: chunks with embeddings in the vector index, `graph/queries.py` functions, and the sample graph for tests.
