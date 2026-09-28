# TRD — Interlock: Technical Requirements Document

| Field | Value |
| --- | --- |
| Document | Technical Requirements Document |
| Version | 1.0 |
| Related | `PRD.md` (what and why), `ARCHITECTURE.md` (structure and flows), `phases/` (build steps) |

> **Accuracy note.** Library and database APIs change. Every code sample here is a **sketch** that shows structure and intent. Before writing real code, check each call against the current official docs. Items marked **Verify** are ones I am not fully certain of.

---

## 1. Technology stack

### 1.1 Decision summary

| Layer | Technology | Status | Why (short) |
| --- | --- | --- | --- |
| Language | Python 3.11+ (backend/pipelines) & TypeScript (frontend) | Required | Best ecosystem for PDF, LLM, graph, eval; Next.js for interactive web app |
| Package manager | uv | Required | Fast, lockfile, simple commands |
| Data models | Pydantic v2 | Required | One typed schema for LLM output, validation, API |
| HTTP client | httpx | Required | Timeouts, retries control, sync/async |
| PDF text | PyMuPDF | Required | Fast, reliable page text |
| PDF tables | pdfplumber | Required | Cell-level table control |
| OCR | Tesseract (via pytesseract) | Optional | Only if scanned PDFs appear |
| Graph DB (+ vectors) | **TigerGraph** (Savanna cloud or Community/Developer edition in Docker; 4.2+ recommended for native vector attributes — **Verify**) | Required (hackathon organiser's platform) | Native parallel graph engine, GSQL multi-hop traversal and accumulators, installed queries |
| Graph query language | GSQL (installed, parameterized queries kept as `.gsql` files) | Required | TigerGraph's query language; versioned in git |
| Graph driver | `pyTigerGraph` (REST++ / GSQL server) | Required | Official Python client: schema, upserts, installed and interpreted queries |
| Entity-name lookup | Turso DB / libSQL FTS5 over `entities` (name + aliases) | Required | TigerGraph has no built-in full-text index (**Verify**); Turso DB already holds every entity |
| Run store | Turso DB / libSQL (`libsql-client` or local libSQL) | Required | Cloud-native deployment with local dev parity |
| LLM access | Own gateway over one provider SDK | Required | Caching, cost, fairness, logging in one place |
| Embeddings | Chosen by recall test (hosted API or sentence-transformers) | Required | Measured on own data |
| Fuzzy matching | RapidFuzz | Required | Fast string similarity |
| Agent | Hand-written state machine with native tool calling | Required | Transparent, fair, educational |
| API | FastAPI + Uvicorn | Recommended | Typed, async, auto docs |
| Dashboard | Next.js (TypeScript, React, Tailwind CSS, Recharts / Plotly.js, React Flow / Cytoscape) | Required | Modern, responsive web dashboard |
| Tests | pytest | Required | Standard |
| Lint/format | Ruff | Required | One fast tool |
| Types | mypy or Pyright | Required | Catches schema mismatches |
| Containers | Docker + Docker Compose | Required | One-command startup |
| CI | GitHub Actions | Recommended | Free for public repos |

Full reasoning, alternatives and trade-offs for every row are in section 1.2.

### 1.2 Decisions with alternatives

| Decision | Alternatives considered | Why not selected | Learning value |
| --- | --- | --- | --- |
| **Python + TypeScript** | Python-only, TypeScript-only, Go | Python has the best tooling for PDF/LLM/evaluation; TypeScript + React/Next.js provides a responsive, stateful frontend without Streamlit rerun overhead | Modern modular web architecture |
| **TigerGraph** | Neo4j; Memgraph; PostgreSQL + Apache AGE; ArangoDB; NetworkX | **Not a free choice: the hackathon is organised by TigerGraph and requires it.** It also suits the project: deep multi-hop traversal with accumulators (e.g. summing pledged stake or transaction values along paths) runs inside the database | Graph modeling, GSQL, accumulators, installed queries |
| **Vectors inside TigerGraph** | Qdrant, pgvector, Chroma, FAISS | Keeps chunk-to-entity links and vector search in one engine. Fallback if the deployed version lacks native vectors (Q-08): a local FAISS/NumPy index keyed by `chunk_id`, everything else stays in TigerGraph | Vector attributes, ANN search |
| **Turso DB FTS5 for entity names** | Lucene-style index in the graph DB, Elasticsearch | TigerGraph has no built-in full-text index; entities are few (thousands) so FTS5 plus RapidFuzz is enough | Full-text search basics |
| **Turso DB run store** | PostgreSQL, DuckDB, local SQLite | Cloud libSQL provides seamless cloud deployment and local dev parity without file lock/mount issues | Relational schema design, cloud DB |
| **PyMuPDF + pdfplumber** | Docling, Unstructured, Camelot, vision LLM | Heavier or narrower; decided by a bake-off in Phase 0 | Document AI realities |
| **Own LLM gateway** | LiteLLM, LangChain model wrappers | Extra dependency; less control over caching and cost. LiteLLM can sit inside the gateway if you switch providers often | Caching, retries, cost control |
| **Hand-written agent** | LangGraph, LlamaIndex agents, CrewAI | Framework prompts and abstractions hide behavior; for a comparison project transparency matters. Move to LangGraph if you need pause/resume or many branches | How agents actually work |
| **Custom GraphRAG** | Microsoft GraphRAG package; TigerGraph's own GraphRAG project (`tigergraph/graphrag`) | They build or assume their own graph structures; ours is typed with provenance. Read TigerGraph's GraphRAG repo for ideas and for the hackathon's expectations (**Verify** APIs), and cite it as related work | Graph retrieval design |
| **FastAPI** | Flask; no API | Flask lacks built-in typing; no-API is acceptable fallback | API design |
| **Next.js** | Streamlit, Gradio, Grafana, plain React SPA | Streamlit script reruns limit complex multi-panel state and graph interaction; Next.js gives full UI control, Tailwind styling, rich network graph canvas, and clean API integration | Modern full-stack architecture |
| **No queue/cache service/K8s** | Redis, Celery, Kubernetes | No need at single-machine scale | Knowing when *not* to add infrastructure |

### 1.3 LLM roles

| Role | Used by | Requirement | Selection guidance |
| --- | --- | --- | --- |
| Extractor | Phase 2–3 | Accurate structured output on long text | Strongest affordable model; run once, cached |
| Answerer | All three pipelines | Tool calling; same model for all | Mid-tier acceptable; fairness first |
| Judge | Evaluation | Consistent grading | Different model family from answerer if possible |
| Helper | Entity linking, relation-type selection, paraphrasing | Cheap, fast | Smallest reliable model |

Model names and prices change often. Put them only in `config/models.yaml` and fill prices from each provider's current pricing page.

---

## 2. Repository structure

```
interlock/
├── README.md
├── LICENSE
├── pyproject.toml
├── uv.lock
├── Makefile
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── .gitignore
├── config/
│   ├── companies.yaml
│   ├── pipeline.yaml
│   └── models.yaml
├── data/
│   ├── raw/                 # gitignored, content-addressed PDFs
│   ├── inbox/               # manual drops
│   ├── parsed/              # gitignored, per-document JSON
│   ├── extracted/           # gitignored, per-document records
│   ├── samples/             # committed small demo graph + cached answers
│   └── cache/llm/           # gitignored LLM response cache
├── db/
│   └── interlock.db         # gitignored local database file (if local libSQL used)
├── src/interlock/
│   ├── __init__.py
│   ├── settings.py
│   ├── cli.py
│   ├── common/              # ids, logging, timing, errors
│   ├── store/               # Turso DB / libSQL access + migrations
│   ├── ingest/              # fetcher, registry, inbox
│   ├── parse/               # pdf text, tables, cleaning, sections, chunking
│   ├── extract/             # schemas, prompts, runner, grounding, validation
│   ├── resolve/             # normalization, matching, merge log
│   ├── graph/               # client, schema (gsql/), loader, queries
│   ├── embed/               # embedding provider + indexing
│   ├── llm/                 # gateway, providers, cache, pricing
│   ├── pipelines/
│   │   ├── base.py
│   │   ├── prompts/
│   │   ├── rag.py
│   │   ├── graphrag/        # linking, expand, serialize, pipeline
│   │   └── agent/           # state, loop, tools, guardrails, calculator, verifier
│   ├── eval/                # questions, generator, scorers, judge, taxonomy, runner, stats
│   └── api/                 # FastAPI app
├── frontend/                # Next.js web dashboard (TypeScript, React, Tailwind CSS)
│   ├── package.json
│   ├── tailwind.config.ts
│   ├── src/
│   │   ├── app/             # App router pages (overview, tradeoffs, failures, inspector, live)
│   │   ├── components/      # UI components (answer card, trace table, subgraph canvas)
│   │   └── lib/             # API client, types, formatters
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
└── docs/
    ├── PRD.md  TRD.md  ARCHITECTURE.md
    ├── phases/
    ├── decisions/           # decision records
    ├── data-quality.md
    └── evaluation.md
```

### 2.1 Module dependency rules

- `common`, `store`, `llm` depend on nothing else in the project.
- `ingest` → `store`.
- `parse` → `store`.
- `extract` → `parse`, `llm`, `store`.
- `resolve` → `extract` models, `store`.
- `graph` → `resolve` models, `store`.
- `embed` → `llm` (if hosted), `graph`.
- `pipelines` → `llm`, `graph`, `embed`, `store`.
- `eval` → `pipelines`, `store`, `llm`.
- `api` → `pipelines`, `eval` (read), `store`.
- `frontend` → `api`.
- No module imports from `api` or `frontend`.

---

## 3. Configuration

All configuration is in YAML under `config/` and secrets in `.env`. `settings.py` loads both into one typed `Settings` object (Pydantic).

### 3.1 `.env.example`

```
LLM_PROVIDER=anthropic            # or openai, google, local
LLM_API_KEY=
JUDGE_API_KEY=                    # if judge uses a different provider
EMBEDDING_API_KEY=                # if using a hosted embedding API
TG_HOST=http://localhost           # or your TigerGraph Savanna URL
TG_GRAPH=Interlock
TG_USERNAME=tigergraph
TG_PASSWORD=change-me
TG_SECRET=                        # optional: for token auth on Savanna (Verify)
TG_RESTPP_PORT=9000               # cloud deployments may use 443 (Verify)
TG_GS_PORT=14240
TURSO_DATABASE_URL=libsql://your-db.turso.io   # or file:db/interlock.db for local dev
TURSO_AUTH_TOKEN=your-auth-token               # optional for local file
LLM_SPEND_CAP_USD=25
LOG_LEVEL=INFO
```

### 3.2 `config/models.yaml`

```yaml
extractor:
  provider: anthropic
  model: "<fill from provider docs>"
  temperature: 0
  max_output_tokens: 4096
answerer:
  provider: anthropic
  model: "<fill>"
  temperature: 0
  max_output_tokens: 1500
judge:
  provider: openai
  model: "<fill>"
  temperature: 0
helper:
  provider: anthropic
  model: "<fill: small model>"
  temperature: 0
embedding:
  provider: local            # or hosted provider name
  model: "<fill after recall test>"
  dimensions: 768            # must match the model; Verify
pricing_usd_per_million_tokens:   # fill from provider pricing pages
  "<model-name>": {input: 0.0, output: 0.0}
```

### 3.3 `config/pipeline.yaml`

```yaml
fetch:
  delay_seconds: 3
  timeout_seconds: 60
  max_retries: 3
  user_agent: "HiddenLinks research project (contact: <your email>)"
parse:
  min_chars_per_page: 200          # below = possible scan
  header_footer_repeat_ratio: 0.6
chunk:
  target_tokens: 500
  max_tokens: 800
  overlap_tokens: 60
extract:
  sections: [governance, related_party, auditor, board_report, subsidiaries, shareholding]
resolve:
  auto_merge_threshold: 95
  review_band_low: 85
retrieval:
  evidence_token_budget: 6000
  rag_top_k: 20
  rerank_top_k: 8
  use_reranker: false
graphrag:
  max_hops: 2
  max_triples: 150
  linked_chunks: 6
agent:
  max_steps: 8
  max_tokens: 40000
  timeout_seconds: 120
  gsql_timeout_seconds: 10
  gsql_max_rows: 200
eval:
  bootstrap_samples: 2000
  numeric_rel_tolerance: 0.01
```

---

## 4. Data models (Pydantic)

These are the canonical contracts. Field names are used identically in Turso DB, the graph, the API and the dashboard.

### 4.1 Documents and chunks

```python
from datetime import date, datetime
from enum import Enum
from pydantic import BaseModel, Field

class DocType(str, Enum):
    ANNUAL_REPORT = "annual_report"
    SHAREHOLDING = "shareholding"
    RPT_DISCLOSURE = "rpt_disclosure"
    REGULATORY_ORDER = "regulatory_order"

class DocumentMeta(BaseModel):
    doc_id: str                  # = sha256 hex
    company_id: str | None       # None for orders naming several companies
    doc_type: DocType
    fiscal_year: str | None      # "FY2023-24" convention everywhere
    source_url: str | None
    file_path: str
    fetched_at: datetime

class Page(BaseModel):
    doc_id: str
    page_no: int                 # 1-based, as printed by the viewer
    text: str
    is_probable_scan: bool = False

class TableCell(BaseModel):
    row: int
    col: int
    text: str

class Table(BaseModel):
    doc_id: str
    page_no: int
    table_idx: int
    cells: list[TableCell]
    caption: str | None = None

class Section(BaseModel):
    doc_id: str
    kind: str                    # governance, related_party, ...
    page_start: int
    page_end: int

class Chunk(BaseModel):
    chunk_id: str                # f"{doc_id[:12]}-{section}-{n}"
    doc_id: str
    company_id: str | None
    fiscal_year: str | None
    section: str
    page_start: int
    page_end: int
    text: str
    token_count: int
```

### 4.2 Extraction records

Every record carries evidence.

```python
class Evidence(BaseModel):
    doc_id: str
    page: int
    quote: str = Field(min_length=8, max_length=600)

class DirectorRecord(BaseModel):
    person_name: str
    din: str | None = None
    company_name: str
    role: str                    # e.g. "Independent Director", "Managing Director"
    is_independent: bool | None
    appointed_on: date | None = None
    ceased_on: date | None = None
    fiscal_year: str
    evidence: Evidence

class ShareholdingRecord(BaseModel):
    holder_name: str
    holder_kind: str             # "person" | "company" | "category"
    company_name: str
    pct_holding: float = Field(ge=0, le=100)
    pct_pledged_of_holding: float | None = Field(default=None, ge=0, le=100)
    is_promoter_group: bool | None
    as_of: date
    evidence: Evidence

class RelatedPartyTxnRecord(BaseModel):
    reporting_company: str
    counterparty_name: str
    relationship: str            # as disclosed, e.g. "Subsidiary", "KMP", "Entity controlled by promoter"
    nature: str                  # e.g. "Sale of goods", "Loan given"
    amount_inr: float = Field(ge=0)   # normalized to rupees
    amount_raw: str              # as printed, e.g. "12.5 (₹ crore)"
    fiscal_year: str
    evidence: Evidence

class AuditorRecord(BaseModel):
    company_name: str
    firm_name: str
    firm_registration_no: str | None = None
    fiscal_year: str
    evidence: Evidence

class SubsidiaryRecord(BaseModel):
    parent_company: str
    subsidiary_name: str
    pct_held: float | None = Field(default=None, ge=0, le=100)
    as_of: date | None
    evidence: Evidence

class RegulatoryActionRecord(BaseModel):
    order_id: str                # regulator's reference or derived id
    regulator: str
    order_date: date
    action_type: str             # e.g. "penalty", "debarment", "warning", "settlement"
    named_entities: list[str]    # people and companies named
    summary: str                 # one neutral sentence
    evidence: Evidence
```

### 4.3 Answer contract

```python
class AnswerType(str, Enum):
    ENTITY = "entity"; LIST = "list"; NUMBER = "number"; DATE = "date"
    YES_NO = "yes_no"; TEXT = "text"; NOT_FOUND = "not_found"

class Status(str, Enum):
    OK = "ok"; ABSTAINED = "abstained"; ERROR = "error"; BUDGET = "budget_exceeded"

class Citation(BaseModel):
    doc_id: str
    page: int
    quote: str

class EvidenceItem(BaseModel):
    kind: str                    # "chunk" | "triple" | "tool_result" | "summary"
    ref_id: str                  # chunk_id, edge id, step id
    text: str

class TraceStep(BaseModel):
    step: int
    kind: str                    # "retrieve" | "llm" | "tool" | "verify"
    name: str
    input_summary: str
    output_summary: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    error: str | None = None

class Usage(BaseModel):
    tokens_in: int; tokens_out: int; cost_usd: float
    latency_ms: int; llm_calls: int; tool_calls: int

class AnswerResult(BaseModel):
    pipeline: str                # "rag" | "graphrag" | "agent"
    question: str
    answer_short: str            # scored value, e.g. "Deloitte Haskins & Sells LLP"
    answer_long: str             # one-paragraph explanation with [doc, p.N] markers
    answer_type: AnswerType
    citations: list[Citation]
    evidence: list[EvidenceItem]
    trace: list[TraceStep]
    usage: Usage
    status: Status
```

---

## 5. Run store schema (Turso DB / libSQL)

```sql
CREATE TABLE IF NOT EXISTS documents (
  doc_id TEXT PRIMARY KEY,               -- sha256
  company_id TEXT,
  doc_type TEXT NOT NULL,
  fiscal_year TEXT,
  source_url TEXT,
  file_path TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'registered',  -- registered|parsed|extracted|failed
  error TEXT
);

CREATE TABLE IF NOT EXISTS fetch_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id TEXT, doc_type TEXT, fiscal_year TEXT,
  url TEXT, attempted_at TEXT, http_status INTEGER, outcome TEXT, error TEXT
);

CREATE TABLE IF NOT EXISTS sections (
  doc_id TEXT, kind TEXT, page_start INTEGER, page_end INTEGER,
  PRIMARY KEY (doc_id, kind, page_start)
);

CREATE TABLE IF NOT EXISTS extraction_runs (
  run_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT,
  model TEXT, prompt_version TEXT, git_commit TEXT, notes TEXT
);

CREATE TABLE IF NOT EXISTS records (
  record_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  doc_id TEXT NOT NULL,
  record_type TEXT NOT NULL,             -- director|shareholding|rpt|auditor|subsidiary|regulatory
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL,                  -- accepted|rejected|review|fixed
  reason TEXT
);

CREATE TABLE IF NOT EXISTS review_queue (
  record_id TEXT PRIMARY KEY,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL,
  decided_at TEXT, decision TEXT, decided_payload_json TEXT
);

CREATE TABLE IF NOT EXISTS entities (
  entity_id TEXT PRIMARY KEY,            -- "P:<din>" | "C:<cin>" | "A:<frn>" | "P:x<hash>" fallback
  kind TEXT NOT NULL,                    -- person|company|audit_firm
  canonical_name TEXT NOT NULL,
  aliases_json TEXT NOT NULL DEFAULT '[]'
);

-- Entity-name search (TigerGraph has no built-in full-text index); rebuilt from `entities` by the build
CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
  entity_id UNINDEXED, kind UNINDEXED, name, aliases
);

CREATE TABLE IF NOT EXISTS merge_log (
  mention_id TEXT PRIMARY KEY,
  entity_id TEXT NOT NULL,
  method TEXT NOT NULL,                  -- din|cin|frn|exact_name|fuzzy|manual
  score REAL,
  reason TEXT
);

CREATE TABLE IF NOT EXISTS questions (
  qid TEXT PRIMARY KEY,
  version TEXT NOT NULL,
  question TEXT NOT NULL,
  category TEXT NOT NULL,
  answer_type TEXT NOT NULL,
  gold_answer_json TEXT NOT NULL,
  gold_evidence_json TEXT NOT NULL,
  split TEXT NOT NULL,                   -- dev|test
  difficulty TEXT,
  template_id TEXT,
  verified INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  pipeline TEXT NOT NULL,
  split TEXT NOT NULL,
  question_version TEXT NOT NULL,
  config_json TEXT NOT NULL,
  git_commit TEXT,
  started_at TEXT, finished_at TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS results (
  run_id TEXT, qid TEXT,
  answer_json TEXT NOT NULL,             -- full AnswerResult
  PRIMARY KEY (run_id, qid)
);

CREATE TABLE IF NOT EXISTS scores (
  run_id TEXT, qid TEXT,
  correct REAL,                          -- 0..1 (F1 for sets)
  faithfulness REAL,
  citation_accuracy REAL,
  evidence_recall REAL,
  abstention_ok INTEGER,
  failure_label TEXT,
  judge_reason TEXT,
  PRIMARY KEY (run_id, qid)
);

CREATE TABLE IF NOT EXISTS traces (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT, pipeline TEXT, step INTEGER, kind TEXT, name TEXT,
  input_summary TEXT, output_summary TEXT,
  tokens_in INTEGER, tokens_out INTEGER, cost_usd REAL, latency_ms INTEGER, error TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS llm_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cache_key TEXT, role TEXT, provider TEXT, model TEXT,
  tokens_in INTEGER, tokens_out INTEGER, cost_usd REAL, latency_ms INTEGER,
  cache_hit INTEGER, error TEXT, created_at TEXT
);
```

Migrations: a `store/migrations/` folder with numbered `.sql` files and a `schema_version` table. Apply in order at startup.

---

## 6. Graph schema (TigerGraph)

One graph named `Interlock` (name from `TG_GRAPH`). The schema is defined in GSQL and kept in `src/interlock/graph/gsql/schema.gsql`. Vertex types correspond to the former "labels"; every vertex has a `PRIMARY_ID` (the key below).

### 6.1 Vertex types and keys

| Vertex type | `PRIMARY_ID` | Other attributes |
| --- | --- | --- |
| `Company` | `entity_id` | `name`, `cin`, `aliases_text`, `exchange_code`, `sector`, `in_dataset` (BOOL) |
| `Person` | `entity_id` | `name`, `din`, `aliases_text` |
| `AuditFirm` | `entity_id` | `name`, `frn`, `aliases_text` |
| `RegulatoryAction` | `order_id` | `regulator`, `order_date`, `action_type`, `summary` |
| `RelatedPartyTxn` | `txn_id` | `fiscal_year`, `nature`, `relationship`, `amount_inr` (DOUBLE), `amount_raw` |
| `Sector` | `name` | — |
| `Document` | `doc_id` | `doc_type`, `fiscal_year`, `source_url` |
| `Chunk` | `chunk_id` | `text`, `section`, `page_start`, `page_end`, `fiscal_year`, `company_id`, `embedding` (vector attribute, see 6.3) |

### 6.2 Edge types

Edges are directed. Every edge that traversals need to walk backwards declares a reverse edge (`WITH REVERSE_EDGE`). Each fact edge uses a `DISCRIMINATOR(edge_id STRING)` so that several edges of the same type between the same two vertices (for example a director serving in several years) stay distinct and re-loading the same `edge_id` overwrites instead of duplicating. **Verify** discriminator and multi-endpoint edge syntax on your version.

| Edge type (reverse) | Pattern | Attributes |
| --- | --- | --- |
| `DIRECTOR_OF` (`HAS_DIRECTOR`) | `Person -> Company` | `role`, `independent`, `start_date`, `end_date`, `fiscal_year` |
| `HOLDS_STAKE` (`HELD_BY`) | `Person -> Company` and `Company -> Company` | `pct`, `pledged_pct`, `promoter_group`, `as_of` |
| `SUBSIDIARY_OF` (`HAS_SUBSIDIARY`) | `Company -> Company` | `pct`, `as_of` |
| `AUDITED_BY` (`AUDITS`) | `Company -> AuditFirm` | `fiscal_year` |
| `PARTY_TO` (`HAS_PARTY`) | `Company -> RelatedPartyTxn` and `Person -> RelatedPartyTxn` | `side` = `reporting`/`counterparty` |
| `NAMED_IN` (`NAMES`) | `Company -> RegulatoryAction` and `Person -> RegulatoryAction` | — |
| `IN_SECTOR` (`SECTOR_OF`) | `Company -> Sector` | — |
| `HAS_CHUNK` (`CHUNK_OF`) | `Document -> Chunk` | — |
| `MENTIONS` (`MENTIONED_IN`) | `Chunk -> Company`, `Chunk -> Person`, `Chunk -> AuditFirm` | — |

Every fact edge (the first six: all except `IN_SECTOR`, `HAS_CHUNK`, `MENTIONS`) also has: `doc_id`, `page`, `quote`, `run_id`. Its `edge_id` is the discriminator. `from` and `to` are reserved words, so date attributes are `start_date` / `end_date`.

### 6.3 Schema, vector attribute and queries (GSQL — **Verify** syntax for your TigerGraph version)

```gsql
CREATE VERTEX Company (PRIMARY_ID entity_id STRING, name STRING, cin STRING,
    aliases_text STRING, exchange_code STRING, sector STRING, in_dataset BOOL) WITH primary_id_as_attribute="true"
CREATE VERTEX Person (PRIMARY_ID entity_id STRING, name STRING, din STRING, aliases_text STRING)
CREATE VERTEX AuditFirm (PRIMARY_ID entity_id STRING, name STRING, frn STRING, aliases_text STRING)
CREATE VERTEX RegulatoryAction (PRIMARY_ID order_id STRING, regulator STRING, order_date STRING,
    action_type STRING, summary STRING)
CREATE VERTEX RelatedPartyTxn (PRIMARY_ID txn_id STRING, fiscal_year STRING, nature STRING,
    relationship STRING, amount_inr DOUBLE, amount_raw STRING)
CREATE VERTEX Sector (PRIMARY_ID name STRING)
CREATE VERTEX Document (PRIMARY_ID doc_id STRING, doc_type STRING, fiscal_year STRING, source_url STRING)
CREATE VERTEX Chunk (PRIMARY_ID chunk_id STRING, text STRING, section STRING, page_start INT,
    page_end INT, fiscal_year STRING, company_id STRING)

CREATE DIRECTED EDGE DIRECTOR_OF (FROM Person, TO Company, DISCRIMINATOR(edge_id STRING),
    role STRING, independent BOOL, start_date STRING, end_date STRING, fiscal_year STRING,
    doc_id STRING, page INT, quote STRING, run_id STRING) WITH REVERSE_EDGE="HAS_DIRECTOR"
-- ...one statement per edge type in 6.2; multi-endpoint edges use
-- (FROM Person, TO Company | FROM Company, TO Company, ...)

CREATE GRAPH Interlock (*)
```

Vector attribute (needs a TigerGraph version with vector support; set the dimension after the embedding model is chosen in Phase 3 — **Verify** syntax):

```gsql
CREATE SCHEMA_CHANGE JOB add_chunk_vector FOR GRAPH Interlock {
  ALTER VERTEX Chunk ADD VECTOR ATTRIBUTE embedding(DIMENSION=768, METRIC="COSINE");
}
RUN SCHEMA_CHANGE JOB add_chunk_vector
```

Installed queries (files under `src/interlock/graph/gsql/queries/`, each installed with `INSTALL QUERY`; parameters are typed, so no string-built queries):

| Query | Purpose |
| --- | --- |
| `entity_neighbors` | k-hop (1–2) expansion from seed vertices, filtered by edge types and fiscal year, capped by `max_triples`; returns triples with `edge_id` and provenance |
| `shared_directors` | Companies (or people) connected through common directors, optionally restricted to a fiscal year |
| `path_between` | Bounded shortest paths between two entities |
| `stake_aggregate` | Accumulator-based totals (e.g. pledged stake or transaction amounts over a subgraph) |
| `chunks_for_entities` | Chunks that `MENTIONS` a set of entities, with page and section |
| `vector_chunks` | Top-k chunks by vector similarity (native vector search if available) |

GSQL accumulators (`SumAccum`, `SetAccum`, ...) do the joins and totals in the database; the numerical and multi-hop question categories rely on them.

**No full-text index in the graph.** Entity-name lookup uses Turso DB FTS5 over the `entities` table (`name`, `aliases`), followed by RapidFuzz re-ranking. `aliases_text` is still stored on vertices (aliases joined by `" | "`) for display and debugging.

---

## 7. Interfaces

### 7.1 LLM gateway

```python
class Message(BaseModel):
    role: str                    # "system" | "user" | "assistant" | "tool"
    content: str | list[dict]

class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict             # JSON Schema

class LLMRequest(BaseModel):
    role: str                    # extractor|answerer|judge|helper
    messages: list[Message]
    tools: list[ToolSpec] = []
    response_schema: dict | None = None   # JSON Schema for structured output
    temperature: float = 0
    max_output_tokens: int = 1500

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict

class LLMResponse(BaseModel):
    text: str
    tool_calls: list[ToolCall] = []
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    cache_hit: bool
    model: str

class LLMGateway:
    def complete(self, req: LLMRequest, request_id: str | None = None) -> LLMResponse: ...
```

Provider adapters implement one method `call(model, req) -> LLMResponse`. Each adapter translates `Message`/`ToolSpec` into that provider's SDK format. **Verify** each provider's current message and tool-calling format.

### 7.2 Pipeline

```python
class Pipeline(Protocol):
    name: str
    def answer(self, question: str, request_id: str) -> AnswerResult: ...
```

### 7.3 Agent tools

| Tool | Arguments (JSON Schema summary) | Returns |
| --- | --- | --- |
| `find_entity` | `name: str`, `kind: "company"|"person"|"audit_firm"|null` | up to 5 `{entity_id, name, kind, score}` |
| `neighbors` | `entity_id: str`, `rel_types: list[str]`, `hops: 1|2`, `fiscal_year: str|null` | list of triples with edge_id and provenance |
| `graph_query` | `query_name: str` (from an allow-list of installed GSQL queries), `params: dict` | rows (max 200) or error text |
| `search_text` | `query: str`, `company_id: str|null`, `fiscal_year: str|null`, `section: str|null`, `k: int≤10` | chunks with ids and pages |
| `calculate` | `expression: str` | number or error |
| `get_evidence` | `ref_id: str` | `{doc_id, page, quote}` |

---

## 8. API specification (FastAPI)

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| GET | `/health` | — | `{tigergraph: bool, turso: bool, llm_key: bool}` |
| POST | `/ask` | `{question, pipeline}` | `AnswerResult` |
| POST | `/compare` | `{question}` | `{request_id, results: {rag, graphrag, agent}}` (each `AnswerResult` or `{status:"error", error}`) |
| GET | `/runs` | — | list of runs |
| GET | `/runs/{run_id}/metrics` | — | per-category metrics with confidence intervals |
| GET | `/runs/{run_id}/results/{qid}` | — | `AnswerResult` + scores |
| GET | `/questions?split=` | — | question list (gold hidden for test unless `?include_gold=true`) |
| GET | `/graph/subgraph?edge_ids=` | — | nodes + edges for visualization |

Errors: JSON `{error_code, message}` with HTTP 400 (bad input), 404, 503 (dependency down), 500.

---

## 9. Performance, cost and resource requirements

| Item | Requirement |
| --- | --- |
| Machine | 16 GB RAM recommended (TigerGraph + embeddings + app; the TigerGraph Docker image is memory-hungry — **Verify** its minimum). Or use TigerGraph Savanna and keep the laptop light. 8 GB workable with a small local embedding model or hosted embeddings |
| TigerGraph resources | Give the container enough memory (start ≥ 8 GB for Docker Desktop — **Verify** current guidance); cloud free tiers have size limits, so check them in Phase 0 |
| Evidence budget | Same token budget for final answer prompts across pipelines (`retrieval.evidence_token_budget`) |
| Agent budget | ≤ 8 tool steps, ≤ 40k tokens, ≤ 120 s per question (tune in Phase 7) |
| GSQL queries | ≤ 10 s per query (request timeout header — **Verify**), ≤ 200 rows returned to the LLM |
| Spend cap | Hard stop in gateway at `LLM_SPEND_CAP_USD` |
| Caching | Every LLM call cached by content hash; eval reruns cost zero if nothing changed |

## 10. Security requirements

| ID | Requirement |
| --- | --- |
| SEC-01 | Secrets only in `.env`; `.env` in `.gitignore`; CI uses repository secrets |
| SEC-02 | Agent graph access: only allow-listed installed read-only GSQL queries with typed parameters; no ad-hoc GSQL from the model; use a read-only TigerGraph role/token for the online layer; enforce row cap and timeout |
| SEC-03 | Calculator: AST whitelist; no `eval`/`exec` |
| SEC-04 | Retrieved document text is wrapped and labeled as untrusted data in all prompts |
| SEC-05 | API binds to localhost by default; basic auth if hosted publicly |
| SEC-06 | Fetcher respects rate limits and terms of use |
| SEC-07 | No personal data beyond public filings |

## 11. Logging and observability requirements

- JSON log lines: `ts, level, component, request_id, event, details`.
- Every LLM call → `llm_calls` row. Every pipeline step → `traces` row.
- Each run records config JSON and git commit.
- `/health` endpoint and a startup check that fails fast with a clear message.

## 12. Testing requirements

| Level | Minimum coverage |
| --- | --- |
| Unit | All normalization, validation, grounding, scoring, calculator, GSQL query allow-list and parameter validation |
| Contract | All Pydantic models round-trip; every pipeline returns a valid `AnswerResult` |
| Integration | Parse→extract→load on 2 fixture PDFs; queries on a fixture graph |
| Regression | Extraction precision on labeled pages; 10-question smoke eval with cached LLM |
| Security | Query-name/parameter injection and prompt-injection fixtures |
| End-to-end | Fresh clone → `docker compose up` → dashboard loads |

CI must run without network LLM access (cache only).

## 13. Coding standards

- Type hints everywhere; mypy/Pyright clean on `src/`.
- Ruff for lint and format.
- Functions do one thing; I/O at the edges; pure functions for logic that needs tests.
- No hard-coded paths, model names or thresholds in code — use `Settings`.
- Every prompt is a versioned file under `prompts/` with a version string stored with results.
- Commit messages: `<area>: <change>` (e.g. `extract: add grounding check`).
