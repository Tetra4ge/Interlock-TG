# CLAUDE.md — Interlock-TG

---

## What is Interlock?

**Interlock** is an Agentic GraphRAG system for Indian corporate governance analysis,
built for the TigerGraph Hackathon. It answers complex natural-language questions about
listed Indian companies (NSE/BSE) by parsing and reasoning across public regulatory
disclosures — Annual Reports, Shareholding Patterns, Related-Party Transaction (RPT)
disclosures, and SEBI/RBI regulatory orders.

Governance risk in listed companies rarely sits isolated inside a single document. It
emerges from interconnected relationships across disclosures:

- A director sitting on multiple boards, one of which faced a regulatory action
- Promoter share pledges distributed across obscure holding companies and subsidiaries
- Material related-party transactions routed through entities sharing common beneficial ownership
- Auditor resignations preceding adverse regulatory scrutiny

Plain vector RAG fails on this domain — it cannot join facts across documents, trace
multi-hop paths, or compute aggregations reliably. **Interlock quantifies and solves this gap.**

---

## Final goal (hackathon deliverables)

1. **Working knowledge graph** — a typed, temporal TigerGraph graph of 50–100 companies,
   3 fiscal years (FY2021-22 through FY2023-24), covering companies, directors, shareholders,
   auditors, transactions, and regulatory actions. Every fact edge carries full provenance
   (document + page + verbatim quote).

2. **Three comparable pipelines** — RAG, GraphRAG, and Agentic GraphRAG, all using the
   same LLM (Groq), same corpus, same evidence budget, and same `AnswerResult` output contract.

3. **Verified evaluation set** — 150–300 questions across 6 categories (single-fact,
   multi-hop, temporal, numerical, global, unanswerable), gold answers verified against PDFs,
   frozen dev/test split.

4. **Honest comparison** — per-category accuracy with bootstrap confidence intervals, cost,
   latency, faithfulness, and failure taxonomy for each pipeline, proving where graph-based
   retrieval wins and why.

5. **Interactive dashboard** — 5 pages for judges: Overview, Trade-offs, Failures, Question
   Inspector (three answers side by side with evidence and agent trace), and Live Ask.

6. **Submission deliverables** — GitHub repo (this one), architecture diagram, demo video,
   metrics dashboard hosted or recorded.

---

## Key features

### Data pipeline
- **Polite document acquisition** — HTTP fetcher with rate limits, backoff, User-Agent;
  manual inbox fallback for sites that block automation
- **Content-addressed storage** — every PDF stored as `data/raw/<sha256>.pdf`; identical
  files deduplicated automatically; no re-downloads
- **PDF parsing** — PyMuPDF for text (preserving page numbers), pdfplumber for table
  structure (row/column alignment)
- **Section detection** — keyword-based locator (with TOC offset correction) finds
  governance reports, related-party notes, auditor reports, shareholding tables across
  varied Indian filing formats
- **Overlapping chunking** — token-limited chunks (500/800 tok target/max) with 60-token
  overlap, section-tagged, deterministic IDs

### LLM extraction
- **6 typed record schemas** (Pydantic v2): Director, Shareholding, RelatedPartyTxn,
  Auditor, Subsidiary, RegulatoryAction — each with Evidence (doc_id + page + quote)
- **Grounding check** — every extracted quote must be found on the stated page
  (RapidFuzz `partial_ratio ≥ 95`); failing records are quarantined, not silently dropped
- **Unit normalization** — detects lakh/crore/million context from table headers;
  unknown unit → review queue (never guesses)
- **Validation rules** — DIN format, date ordering, percentage bounds, holding sum checks
- **LLM gateway** — content-hash disk cache, spend cap ($25 default), 5-retry exponential
  backoff, every call logged with tokens + cost; `LLM_OFFLINE=true` for CI

### Entity resolution
- Union-Find clustering over mentions from all accepted records
- Priority: official ID (DIN/CIN/FRN) → exact normalized name → fuzzy ≥ 95 → review
- Conflict detection: cluster with two different official IDs is split and queued
- Result: canonical entity IDs used consistently across the graph

### Knowledge graph (TigerGraph)
- **GSQL schema** — `Company`, `Person`, `AuditFirm`, `Document`, `Chunk`,
  `RelatedPartyTxn` vertices; `DIRECTOR_OF`, `AUDITED_BY`, `PARTY_TO`, `HAS_CHUNK`,
  `MENTIONS` edges with discriminators for temporal multi-edges
- **Installed GSQL queries** — `entity_neighbors`, `shared_directors`, `path_between`,
  `stake_aggregate`, `chunks_for_entities`, `get_edge_by_id`; compiled once, called
  safely as parameterized REST endpoints (no string-built queries)
- **Provenance invariant** — every fact edge carries `doc_id + page + quote + run_id`;
  zero provenance-missing edges enforced by a sanity query
- **One-command rebuild** — `hl build-graph` runs migrate → schema → parse → sections
  → chunk → extract → resolve → load → mentions → embed → entity-index; resumable
  with `--from <step>`

### Vector search
- Embedding model: **all-MiniLM-L6-v2** (sentence-transformers, 384 dims, local,
  no API cost, no query prefix required)
- Index: **local NumPy `.npz`** at `data/vectors/` (TigerGraph native vector support
  not available in the deployed version; ADR-0011)
- Retrieval: vector search + BM25 keyword fusion via reciprocal rank fusion; optional
  cross-encoder rerank

### Three answer pipelines (shared contract)
All pipelines return `AnswerResult(pipeline, question, answer_short, answer_long,
answer_type, citations, evidence, trace, usage, status)`.

| Pipeline | Mechanism | Target queries |
|---|---|---|
| **RAG** | Vector + keyword fusion → rerank → fit to 4000-token budget → single LLM call | Single-fact lookups |
| **GraphRAG** | Plan call → entity linking → `expand_hop` GSQL (1–2 hops) → ranked triples + linked chunks → single answer call; vector fallback | 1–2 hop structural relationships |
| **Agentic GraphRAG** | Tool loop (find_entity, neighbors, graph_query, search_text, calculate, get_evidence) under step/token/time budgets → shared final answer → claim-level verifier | Multi-hop trails, aggregations, temporal cascades |

### Evaluation (Phase 5)
- 6 question categories: `single_fact`, `multi_hop`, `temporal`, `numerical`, `global`,
  `unanswerable`
- Scorers: exact match (entity), set F1 (list), numeric tolerance (number), abstention,
  citation accuracy, evidence recall
- LLM judge: calibrated faithfulness and free-text correctness scoring (separate model
  family from answerer)
- Failure taxonomy: `retrieval_miss`, `entity_link_error`, `missed_hop`,
  `temporal_error`, `arithmetic_error`, `hallucination`, `wrong_abstention`,
  `bad_query`, `budget_loop`, `data_error`
- Bootstrap 95% confidence intervals per category; paired difference test across pipelines

### Dashboard (Phase 8, Next.js 14)
Five pages for judges:
1. **Overview** — accuracy by category, all three pipelines
2. **Trade-offs** — cost vs accuracy scatter, latency distributions
3. **Failures** — failure taxonomy per pipeline
4. **Question Inspector** — one question, three answers, evidence blocks, agent trace steps
5. **Live Ask** — freeform question → three pipeline answers in real time

---

## Project layout

```
Interlock-TG/
├── server/               # Python backend (all business logic)
│   ├── cli.py            # Entry point: `hl <command>`
│   ├── settings.py       # Typed Settings from .env + YAML
│   ├── common/           # Logging, IDs, timing
│   ├── store/            # Turso/libSQL: connect(), migrate(), migrations/*.sql
│   ├── ingest/           # Data acquisition: fetcher, registry, inbox, sources
│   ├── parse/            # PDF → pages/tables/sections/chunks
│   ├── extract/          # LLM extraction: schemas, runner, grounding, validation
│   ├── resolve/          # Entity resolution: normalize, match, cluster (Union-Find)
│   ├── graph/            # TigerGraph: client, schema, loader, queries, export
│   │   └── gsql/         # schema.gsql + queries/*.gsql + queries.lock
│   ├── embed/            # Vector index: provider (all-MiniLM-L6-v2), index, query
│   ├── llm/              # LLM gateway: cache, pricing, providers (Groq), gateway
│   ├── pipelines/        # Answer pipelines: rag.py, graphrag/, agent/, base, models, common/
│   ├── eval/             # Evaluation: models, scorers, runner, stats, judge, taxonomy, persist, compare
│   └── reporting/        # Quality reports
├── dashboard/            # Next.js 14 frontend (App Router, TypeScript, Tailwind)
├── config/
│   ├── companies.yaml    # 5 pilot companies (Tata Motors, Bajaj Finance, etc.)
│   ├── models.yaml       # LLM pricing table (Groq free tier)
│   └── pipeline.yaml     # All tunable parameters (chunk size, top_k, thresholds)
├── data/
│   ├── inbox/            # Drop PDFs here for manual ingestion
│   ├── parsed/           # Intermediate JSON from PDF parser
│   ├── chunks/           # {doc_id}_chunks.json per document
│   └── vectors/          # NumPy .npz vector index
├── db/                   # Local libSQL database file
├── docs/                 # Architecture, PRD, TRD, phase plans, coverage reports
├── phases/               # Phase-by-phase implementation plans (0–10)
├── tests/
│   ├── unit/             # Pure logic tests (no network, no DB)
│   └── integration/      # Marked `@pytest.mark.integration`; skipped by default
└── spikes/               # One-off experiments (parser bake-off)
```

---

## Running the project

### Prerequisites
- Python 3.11+, `uv` installed
- Node.js 18+ and `npm` (for the dashboard)
- A running TigerGraph instance (Docker or Savanna cloud)
- A free Groq API key

### Environment setup

```bash
cp .env.example .env
# Fill in: TG_HOST, TG_PASSWORD, TG_SECRET (Savanna) or leave blank (Docker),
#          TG_GRAPH=Interlock, GROQ_API_KEY, TURSO_DATABASE_URL=file:db/interlock.db
uv sync
```

### Offline build pipeline (run in order)

```bash
uv run hl db-migrate            # create/migrate Turso DB schema
uv run hl fetch                 # discover documents (logs manual_needed; all are manual for now)
uv run hl ingest-inbox          # register PDFs dropped in data/inbox/
uv run hl coverage              # generate docs/coverage.md

uv run hl parse                 # PDF → data/parsed/{doc_id}.json
uv run hl detect-sections       # detect governance/rpt/auditor/etc. sections
uv run hl chunk                 # section text → overlapping chunks in data/chunks/

uv run hl extract --run-id run1 # LLM extraction of typed records
uv run hl review                # interactive CLI review queue
uv run hl evaluate --run-id run1

uv run hl build-graph           # full rebuild: migrate→schema→parse→sections→chunk→
                                #               extract→resolve→load→mentions→embed→entity-index
uv run hl build-graph --from load   # restart from a specific step
uv run hl build-graph --reset-graph --yes  # wipe TigerGraph first

uv run hl export-sample         # export 10–15 companies → data/samples/
uv run hl import-sample         # load sample back into a clean TigerGraph

uv run hl quality               # generate docs/data-quality.md
```

### Online layer

```bash
uv run hl ask "Who audited Tata Motors in FY2023-24?" --pipeline rag
uv run hl ask "Which independent director of Tata Steel also sits on Tata Motors' board?" --pipeline graphrag
uv run hl eval --pipeline rag --split test
uv run hl eval --pipeline graphrag --split dev
uv run hl ask "Who audited Tata Steel in FY2023-24?" --pipeline agent
uv run hl eval --pipeline agent --split dev
uv run hl compare --a <run_id> --b <run_id>      # paired A-B per category, 95% bootstrap CI
```

### Dashboard

```bash
cd dashboard
npm install
npm run dev         # http://localhost:3000
```

---

## Key technical decisions

### Storage split
| Store | Purpose |
|---|---|
| **TigerGraph** | Graph vertices/edges + installed GSQL queries for traversal/aggregation |
| **Turso/libSQL** (`db/interlock.db`) | Documents, records, entities, runs, scores, traces, LLM call log, FTS5 entity index |
| **Filesystem** | Raw PDFs (`data/raw/`), parsed JSON, chunk JSON, `.npz` vector index, LLM disk cache |

### Vector search
TigerGraph native vector support was unavailable in the deployed version (ADR-0011
pending). Vector search falls back to a **local NumPy `.npz` index** at
`data/vectors/all-MiniLM-L6-v2_index.npz`. Chunks are fetched from TigerGraph by ID
after the local nearest-neighbour search. The index is rebuilt by `embed` step in
`build-graph`.

Embedding model: **all-MiniLM-L6-v2** (sentence-transformers, 384 dims, local, no cost,
no query prefix needed).

### LLM gateway
All LLM calls flow through `server/llm/gateway.py`:
- Content-hash disk cache (zero cost on reruns)
- Spend cap (`LLM_SPEND_CAP_USD`, default $25)
- Exponential backoff + jitter (max 5 retries)
- Every call logged to `llm_calls` table (for cost tracking and reproducibility)
- `LLM_OFFLINE=true` → cache-only mode for CI/tests (raises on miss)

Provider: **Groq** only (`server/llm/providers/groq_provider.py`). Model in use:
`openai/gpt-oss-20b` (free tier). See `config/models.yaml` for pricing table.

### TigerGraph authentication
Cloud (Savanna): the standard `pyTigerGraph.getToken()` fails because TG Cloud's gateway
validates the Basic-auth header before reading the body. `server/graph/client.py`
bypasses it with a direct POST to `/gsql/v1/tokens` and attaches the JWT manually.
Docker: standard `createSecret()` + `getToken()` works fine.

### Entity resolution
Union-Find clustering over mentions extracted from all records. Priority:
1. Official ID (DIN for persons, CIN for companies, FRN for audit firms) → certain merge
2. Exact normalized name within block → high confidence
3. Fuzzy match ≥ 95 (RapidFuzz `token_sort_ratio`) + compatible initials → auto-merge
4. Score 85–95 → review queue
5. Otherwise new entity with hash ID (`P:x<hash>`, `C:x<hash>`, `A:x<hash>`)

Never merge two mentions with different official IDs.

### RAG pipeline
`server/pipelines/rag.py`: vector search (k=40) + BM25 keyword fusion via
`reciprocal_rank_fusion` → optional cross-encoder rerank (top 8) → fit to 4000-token
evidence budget → shared final-answer prompt → citation validation.

### GraphRAG pipeline
`server/pipelines/graphrag/`: `plan_question` (helper call → mentions, relation types,
fiscal years, `is_global`) → `link_entities` (FTS5 + RapidFuzz, ambiguity band) →
`choose_relations` (model ∪ keyword rules) → `expand` (installed `expand_hop` query, 2 hops,
per-seed fan-out, hubs skipped at hop 2) → `rank_and_cap` → `serialize` (names + provenance) →
`linked_text` → `split_budget` (60% triples) → shared `final_answer`. Global questions use the
statistics pack in `graph/stats.py`. If nothing links, expansion fails, or the subgraph is
empty, it falls back to RAG's vector retrieval and records the reason in the trace. Parameters,
deviations from the plan and known gaps: `docs/decisions/0013-graphrag-params.md`.

`expand_hop.gsql` has not been installed against a live TigerGraph yet; run
`hl build-graph --from schema` once the cluster is reachable.

### Agentic GraphRAG pipeline
`server/pipelines/agent/`: `run_loop` lets the model pick tools while the code enforces
`Budget` (steps, cumulative tokens, wall clock; exceeding one ends as `budget_exceeded`, not an
error), refuses identical repeated calls, and drops `graph_query` after 2 failures. Tools
(`tools/`) validate arguments with Pydantic, never raise, and log every fact to the
`EvidenceLog` as `E1..` (same labels as RAG/GraphRAG). `graph_query` is an allow-list of 4
installed queries with typed, `fullmatch`-validated parameters (`guardrails.py`): the model
never writes query text. `calculate` is an AST whitelist (`calculator.py`). The final answer is
the shared `final_answer` over the evidence log; `verifier.py` then checks each claim (and
numeric answers against the evidence), buys one more agent cycle, and otherwise drops unsupported
claims. Parameters, deviations and verified/unverified status:
`docs/decisions/0014-agent-params.md`.

Provider quirk: Groq validates tool calls against the JSON Schema server-side and answers
400 "Tool call validation failed" when the model's arguments don't fit. The loop treats that
as a retry request (max 2), and tool schemas accept the id forms the model is shown (e.g.
`C:TATASTEEL` for `company_id`).

---

## Graph schema (TigerGraph)

Vertex types: `Company`, `Person`, `AuditFirm`, `Document`, `Chunk`, `RelatedPartyTxn`

Edge types:
| Edge | From → To | Key attributes |
|---|---|---|
| `DIRECTOR_OF` | Person → Company | `role`, `independent`, `start_date`, `end_date`, `fiscal_year`, `doc_id`, `page`, `quote`, `run_id`, `edge_id` |
| `AUDITED_BY` | Company → AuditFirm | — |
| `PARTY_TO` | Company/Person → RelatedPartyTxn | `side` (reporting/counterparty), `doc_id`, `page`, `run_id`, `edge_id` |
| `HAS_CHUNK` | Document → Chunk | — |
| `MENTIONS` | Chunk → Company/Person/AuditFirm | — |

Installed GSQL queries (in `server/graph/gsql/queries/`):
- `entity_neighbors` — bounded N-hop expansion
- `shared_directors` — common directors between companies
- `path_between` — shortest path (max 3 hops)
- `stake_aggregate` — sum promoter pledge %
- `chunks_for_entities` — linked text chunks for a set of entities
- `get_edge_by_id` — provenance lookup for citations

Schema changes: freeze schema before loading data. Adding columns requires a GSQL
schema-change job. To reset: `hl build-graph --reset-graph --yes` wipes and rebuilds.

---

## Extraction schemas

Defined in `server/extract/schemas.py` (Pydantic v2):

- `DirectorRecord` — person, DIN, company, role, independent, appointed_on, ceased_on
- `ShareholdingRecord` — holder, kind, company, pct_holding, pct_pledged, is_promoter
- `RelatedPartyTxnRecord` — reporting company, counterparty, relationship, nature, amount_inr, amount_raw
- `AuditorRecord` — company, firm name, FRN
- `SubsidiaryRecord` — parent, subsidiary, pct_held
- `RegulatoryActionRecord` — order_id, regulator, date, action_type, named_entities, summary

Every record carries an `Evidence(doc_id, page, quote)`. Grounding check ensures the
quote appears on the stated page (exact match or `partial_ratio ≥ 95` via RapidFuzz).
Records failing grounding → `status='rejected'`.

---

## Turso DB schema (key tables)

| Table | Purpose |
|---|---|
| `documents` | Registered PDFs: `doc_id` (SHA256), `company_id`, `doc_type`, `fiscal_year`, `status` |
| `fetch_attempts` | Per-target fetch log |
| `sections` | Detected section ranges per document |
| `extraction_runs` | Run metadata: model, prompt version, git commit |
| `records` | Extracted typed records with `payload_json` and `status` |
| `review_queue` | Records awaiting manual review |
| `entities` | Resolved entities: `entity_id`, `kind`, `canonical_name`, `aliases_text` |
| `entities_fts` | FTS5 virtual table for fast entity name lookup |
| `merge_log` | Per-mention resolution audit: `mention_id`, `entity_id`, `method`, `score` |
| `llm_calls` | Every LLM call: `cache_key`, `model`, tokens, cost, latency, `cache_hit` |
| `traces` | Pipeline execution trace steps |
| `questions` | Evaluation question set (phases 5+) |
| `runs` | Eval run metadata |
| `results` | Raw pipeline answers per question/run |
| `scores` | Computed scores per question/run |

Migrations in `server/store/migrations/`. Add `000N_description.sql` for new columns;
`migrate()` applies them in order.

---

## Configuration

All tunable parameters live in `config/pipeline.yaml` (loaded as typed config in
`server/pipelines/config.py`):

```yaml
chunk:       target_tokens: 500, max_tokens: 800, overlap_tokens: 60
extract:     sections: [governance, related_party, auditor, board_report, ...]
resolve:     auto_merge_threshold: 95, review_band_low: 85
retrieval:   evidence_token_budget: 4000, rag_top_k: 40, rerank_top_k: 8, use_reranker: true
graphrag:    max_hops: 2, max_triples: 150, linked_chunks: 6
agent:       max_steps: 8, max_tokens: 40000, timeout_seconds: 120
eval:        bootstrap_samples: 2000, numeric_rel_tolerance: 0.01
```

Secrets and infrastructure settings are in `.env` (never committed). See `.env.example`
for the full list of variables.

---

## Testing

```bash
uv run pytest -q                                    # unit tests only (default)
uv run pytest -m integration                        # integration tests (needs live TG + LLM)
uv run pytest tests/unit/test_gateway.py -v         # single file
```

Integration tests are excluded by default (`pyproject.toml: addopts = "-m 'not integration'"`).
They require a live TigerGraph connection and may consume API credits.

LLM tests use the offline cache. If a test makes a real LLM call unexpectedly, check
that `LLM_OFFLINE=true` is set in `.env` or that the `settings.llm_offline` mock is in
place.

---

## Pilot dataset

5 companies chosen for diversity (see `config/companies.yaml`):

| company_id | Name | Sector | Reason |
|---|---|---|---|
| TATAMOTORS | Tata Motors Limited | Automobiles | Large group, many subsidiaries |
| BAJFINANCE | Bajaj Finance Limited | Financial Services (NBFC) | Named in RBI order 2023 |
| TATASTEEL | Tata Steel Limited | Metals & Mining | Different sector |
| TRF | TRF Limited | Industrial Machinery | Small-cap, messier PDFs |
| BAJAJFINSV | Bajaj Finserv Limited | Financial Services (Holding) | Holding company structure |

Fiscal years: FY2021-22, FY2022-23, FY2023-24.

All document acquisition is **manual** — drop PDFs into `data/inbox/` with the naming
convention `<COMPANY_ID>__<doc_type>__<FY>.pdf` (e.g.
`TATAMOTORS__annual_report__FY2023-24.pdf`), then run `hl ingest-inbox`.

---

## Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `OfflineCacheMiss` in tests | LLM test hit real API | Set `LLM_OFFLINE=true` in `.env` or mock settings |
| `getToken()` 401 on Savanna | pyTigerGraph adds Basic-auth header | `client.py` uses `_mint_cloud_token()` which bypasses it |
| Vector index not found | `build-graph` embed step not run | Run `uv run hl build-graph --from embed` |
| FTS query crash on entity names | Unescaped FTS5 syntax chars | `graph/queries.py` wraps text in quoted phrase |
| Duplicate edges on graph rebuild | Missing discriminator or non-deterministic edge_id | Each edge uses `sha256(record_id + rel_type)[:16]` as `edge_id` |
| Schema change fails | Data already loaded | Freeze schema early; for breaking changes use `--reset-graph` |
| Coverage report shows all manual_needed | Exchange adapter stubs return `[]` by design | Manual download into `data/inbox/` is the intended workflow |
| GraphRAG answers look identical to RAG | `expand_hop` failed and the pipeline fell back to vector evidence | Check the trace for a `fallback` step and its error; confirm TigerGraph is reachable and the query is installed |
| Agent answers `not_found` on easy questions | Graph tools failing (query not installed / graph missing) leaves only `search_text`, and the 20B model searches badly | Check the trace for `neighbors` errors; `hl build-graph --from schema`; confirm `TG_GRAPH` names a graph that exists |
| Agent run fails with a 400 about tool schema | Model arguments don't fit a tool's JSON Schema | Loosen the schema or normalise in the tool (see `search_text`); the loop already retries twice |
| `ModuleNotFoundError: fitz` | Wrong PyMuPDF import | The import name is `fitz` (PyMuPDF < 1.25) or `pymupdf` (newer) |

---

## Style and conventions

- Python 3.11+, Pydantic v2, `uv` for package management
- Ruff for linting (`line-length=100`, `select=["E","F","I","B","UP","SIM"]`)
- Mypy with `disallow_untyped_defs=true` (strict on function signatures)
- All paths resolved from `server/settings.py::ROOT` (project root), never hardcoded
- Fiscal years always as `FY2023-24` (never `FY24`, `2023-24`, or `24`)
- Edge IDs always deterministic: `hashlib.sha256(f"{record_id}:{rel}".encode()).hexdigest()[:16]`
- Every fact edge must carry `doc_id + page + quote + run_id` (provenance invariant)
- LLM prompts versioned (`_v1.md`); never edit in place after producing stored results
- Integration tests marked with `@pytest.mark.integration`; never run on CI without explicit `-m integration`

---

## Git workflow

After completing each phase or task:

1. Stage and commit all changes using **conventional commit format**:
   - `feat:` — new feature or capability
   - `fix:` — bug fix
   - `chore:` — tooling, config, dependency updates
   - `refactor:` — restructuring without behaviour change
   - `docs:` — documentation only
   - `test:` — adding or fixing tests

2. Keep commit messages **short and precise** — describe only what was actually changed.

3. Example:
   ```
   feat: add evaluation scorers and bootstrap CI stats
   ```

4. Push to the branch specified by the user. Create it if it doesn't exist:
   ```bash
   git checkout -b feat/phase-5-eval   # or whatever branch is asked for
   git push origin feat/phase-5-eval
   ```

5. **Never open a PR or merge** unless explicitly asked.

### Pull requests

When asked to raise a PR:
- Title format: `<type>: <short description> - (Phase N)`
  - Example: `feat: add evaluation set, scorers and runner - (Phase 5)`
- Body: Summary bullets + Test plan checklist
- End the PR description with: `🤖 Generated with [Claude Code](https://claude.com/claude-code)`
