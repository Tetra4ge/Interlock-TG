# TRD — Hidden Links: Technical Requirements Document

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
| Language | Python 3.11+ | Required | Best ecosystem for PDF, LLM, graph, eval, dashboard |
| Package manager | uv | Required | Fast, lockfile, simple commands |
| Data models | Pydantic v2 | Required | One typed schema for LLM output, validation, API |
| HTTP client | httpx | Required | Timeouts, retries control, sync/async |
| PDF text | PyMuPDF | Required | Fast, reliable page text |
| PDF tables | pdfplumber | Required | Cell-level table control |
| OCR | Tesseract (via pytesseract) | Optional | Only if scanned PDFs appear |
| Graph DB + vectors | Neo4j 5.x Community | Required | Cypher paths, built-in vector + full-text indexes |
| Graph driver | Official `neo4j` Python driver | Required | Supported, transactional |
| Run store | SQLite (stdlib `sqlite3`) | Required | Zero setup |
| LLM access | Own gateway over one provider SDK | Required | Caching, cost, fairness, logging in one place |
| Embeddings | Chosen by recall test (hosted API or sentence-transformers) | Required | Measured on own data |
| Fuzzy matching | RapidFuzz | Required | Fast string similarity |
| Agent | Hand-written state machine with native tool calling | Required | Transparent, fair, educational |
| API | FastAPI + Uvicorn | Recommended | Typed, async, auto docs |
| Dashboard | Streamlit (+ Plotly charts, pyvis graph view) | Required | Python-only dashboard |
| Tests | pytest | Required | Standard |
| Lint/format | Ruff | Required | One fast tool |
| Types | mypy or Pyright | Required | Catches schema mismatches |
| Containers | Docker + Docker Compose | Required | One-command startup |
| CI | GitHub Actions | Recommended | Free for public repos |

Full reasoning, alternatives and trade-offs for every row are in section 1.2.

### 1.2 Decisions with alternatives

| Decision | Alternatives considered | Why not selected | Learning value |
| --- | --- | --- | --- |
| **Python** | TypeScript, Go, Java | Weaker PDF/table and evaluation tooling; second language for the dashboard | Typed Python, packaging, async |
| **Neo4j** | Memgraph; PostgreSQL + Apache AGE; ArangoDB; NetworkX | Smaller ecosystem; less mature graph tooling; own query language; no persistence/query language | Graph modeling, Cypher, indexes |
| **Vectors inside Neo4j** | Qdrant, pgvector, Chroma, FAISS | Doubles storage; breaks direct chunk-to-entity links. Revisit only if vector search is too slow | Vector indexes, ANN search |
| **SQLite run store** | PostgreSQL, DuckDB | Postgres is overkill; DuckDB optional later for analytics | Relational schema design |
| **PyMuPDF + pdfplumber** | Docling, Unstructured, Camelot, vision LLM | Heavier or narrower; decided by a bake-off in Phase 0 | Document AI realities |
| **Own LLM gateway** | LiteLLM, LangChain model wrappers | Extra dependency; less control over caching and cost. LiteLLM can sit inside the gateway if you switch providers often | Caching, retries, cost control |
| **Hand-written agent** | LangGraph, LlamaIndex agents, CrewAI | Framework prompts and abstractions hide behavior; for a comparison project transparency matters. Move to LangGraph if you need pause/resume or many branches | How agents actually work |
| **Custom GraphRAG** | Microsoft GraphRAG package; `neo4j-graphrag` package | They build or assume their own graph structures; ours is typed with provenance. Read them for ideas (**Verify** APIs) | Graph retrieval design |
| **FastAPI** | Flask; no API | Flask lacks built-in typing; no-API is acceptable fallback | API design |
| **Streamlit** | React/Next.js, Gradio, Grafana | Much more work; weaker dashboards; ops-focused | Data visualization |
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
hidden-links/
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
│   └── hidden_links.sqlite  # gitignored run store
├── src/hidden_links/
│   ├── __init__.py
│   ├── settings.py
│   ├── cli.py
│   ├── common/              # ids, logging, timing, errors
│   ├── store/               # SQLite access + migrations
│   ├── ingest/              # fetcher, registry, inbox
│   ├── parse/               # pdf text, tables, cleaning, sections, chunking
│   ├── extract/             # schemas, prompts, runner, grounding, validation
│   ├── resolve/             # normalization, matching, merge log
│   ├── graph/               # client, schema, loader, queries
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
├── dashboard/
│   ├── app.py
│   └── pages/
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
- `dashboard` → `api` (or `store` + `pipelines` if API is dropped).
- No module imports from `api` or `dashboard`.

---

## 3. Configuration

All configuration is in YAML under `config/` and secrets in `.env`. `settings.py` loads both into one typed `Settings` object (Pydantic).

### 3.1 `.env.example`

```
LLM_PROVIDER=anthropic            # or openai, google, local
LLM_API_KEY=
JUDGE_API_KEY=                    # if judge uses a different provider
EMBEDDING_API_KEY=                # if using a hosted embedding API
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=change-me
SQLITE_PATH=db/hidden_links.sqlite
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
  cypher_timeout_seconds: 10
  cypher_max_rows: 200
eval:
  bootstrap_samples: 2000
  numeric_rel_tolerance: 0.01
```

---

## 4. Data models (Pydantic)

These are the canonical contracts. Field names are used identically in SQLite, the graph, the API and the dashboard.

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

## 5. Run store schema (SQLite)

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

## 6. Graph schema (Neo4j)

### 6.1 Nodes and keys

| Label | Key property | Other properties |
| --- | --- | --- |
| `Company` | `entity_id` | `name`, `cin`, `aliases`, `exchange_code`, `sector` |
| `Person` | `entity_id` | `name`, `din`, `aliases` |
| `AuditFirm` | `entity_id` | `name`, `frn`, `aliases` |
| `RegulatoryAction` | `order_id` | `regulator`, `order_date`, `action_type`, `summary` |
| `RelatedPartyTxn` | `txn_id` | `fiscal_year`, `nature`, `relationship`, `amount_inr`, `amount_raw` |
| `Sector` | `name` | — |
| `Document` | `doc_id` | `doc_type`, `fiscal_year`, `source_url` |
| `Chunk` | `chunk_id` | `text`, `section`, `page_start`, `page_end`, `fiscal_year`, `company_id`, `embedding` |

### 6.2 Relationships

| Type | Pattern | Properties |
| --- | --- | --- |
| `DIRECTOR_OF` | `(Person)-[:DIRECTOR_OF]->(Company)` | `role`, `independent`, `from`, `to`, `fiscal_year` |
| `HOLDS_STAKE` | `(Person|Company)-[:HOLDS_STAKE]->(Company)` | `pct`, `pledged_pct`, `promoter_group`, `as_of` |
| `SUBSIDIARY_OF` | `(Company)-[:SUBSIDIARY_OF]->(Company)` | `pct`, `as_of` |
| `AUDITED_BY` | `(Company)-[:AUDITED_BY]->(AuditFirm)` | `fiscal_year` |
| `PARTY_TO` | `(Company|Person)-[:PARTY_TO]->(RelatedPartyTxn)` | `side` = `reporting`/`counterparty` |
| `NAMED_IN` | `(Company|Person)-[:NAMED_IN]->(RegulatoryAction)` | — |
| `IN_SECTOR` | `(Company)-[:IN_SECTOR]->(Sector)` | — |
| `HAS_CHUNK` | `(Document)-[:HAS_CHUNK]->(Chunk)` | — |
| `MENTIONS` | `(Chunk)-[:MENTIONS]->(Company|Person|AuditFirm)` | — |

Every fact relationship (the first six: all except `IN_SECTOR`, `HAS_CHUNK`, `MENTIONS`) also has: `doc_id`, `page`, `quote`, `run_id`, `edge_id`.

### 6.3 Constraints and indexes (Cypher, Neo4j 5 syntax — **Verify** for your version)

```cypher
CREATE CONSTRAINT company_id IF NOT EXISTS FOR (n:Company) REQUIRE n.entity_id IS UNIQUE;
CREATE CONSTRAINT person_id IF NOT EXISTS FOR (n:Person) REQUIRE n.entity_id IS UNIQUE;
CREATE CONSTRAINT auditfirm_id IF NOT EXISTS FOR (n:AuditFirm) REQUIRE n.entity_id IS UNIQUE;
CREATE CONSTRAINT action_id IF NOT EXISTS FOR (n:RegulatoryAction) REQUIRE n.order_id IS UNIQUE;
CREATE CONSTRAINT rpt_id IF NOT EXISTS FOR (n:RelatedPartyTxn) REQUIRE n.txn_id IS UNIQUE;
CREATE CONSTRAINT sector_name IF NOT EXISTS FOR (n:Sector) REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT doc_id IF NOT EXISTS FOR (n:Document) REQUIRE n.doc_id IS UNIQUE;
CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (n:Chunk) REQUIRE n.chunk_id IS UNIQUE;

CREATE FULLTEXT INDEX entity_names IF NOT EXISTS
FOR (n:Company|Person|AuditFirm) ON EACH [n.name, n.aliases_text];

CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS
FOR (c:Chunk) ON (c.embedding)
OPTIONS { indexConfig: { `vector.dimensions`: 768, `vector.similarity_function`: 'cosine' } };
```

`aliases_text` is a single string of aliases joined by `" | "`, because full-text indexes index string properties.

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
| `graph_query` | `cypher: str` | rows (max 200) or error text |
| `search_text` | `query: str`, `company_id: str|null`, `fiscal_year: str|null`, `section: str|null`, `k: int≤10` | chunks with ids and pages |
| `calculate` | `expression: str` | number or error |
| `get_evidence` | `ref_id: str` | `{doc_id, page, quote}` |

---

## 8. API specification (FastAPI)

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| GET | `/health` | — | `{neo4j: bool, sqlite: bool, llm_key: bool}` |
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
| Machine | 16 GB RAM recommended (Neo4j + embeddings + app). 8 GB workable with a small local embedding model or hosted embeddings |
| Neo4j memory | Set heap and page cache explicitly in Compose; start around 1–2 GB each and adjust |
| Evidence budget | Same token budget for final answer prompts across pipelines (`retrieval.evidence_token_budget`) |
| Agent budget | ≤ 8 tool steps, ≤ 40k tokens, ≤ 120 s per question (tune in Phase 7) |
| Cypher | ≤ 10 s per query, ≤ 200 rows |
| Spend cap | Hard stop in gateway at `LLM_SPEND_CAP_USD` |
| Caching | Every LLM call cached by content hash; eval reruns cost zero if nothing changed |

## 10. Security requirements

| ID | Requirement |
| --- | --- |
| SEC-01 | Secrets only in `.env`; `.env` in `.gitignore`; CI uses repository secrets |
| SEC-02 | Agent Cypher: reject write/admin clauses; enforce LIMIT; read transactions; timeout |
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
| Unit | All normalization, validation, grounding, scoring, calculator, Cypher-guard functions |
| Contract | All Pydantic models round-trip; every pipeline returns a valid `AnswerResult` |
| Integration | Parse→extract→load on 2 fixture PDFs; queries on a fixture graph |
| Regression | Extraction precision on labeled pages; 10-question smoke eval with cached LLM |
| Security | Cypher injection and prompt-injection fixtures |
| End-to-end | Fresh clone → `docker compose up` → dashboard loads |

CI must run without network LLM access (cache only).

## 13. Coding standards

- Type hints everywhere; mypy/Pyright clean on `src/`.
- Ruff for lint and format.
- Functions do one thing; I/O at the edges; pure functions for logic that needs tests.
- No hard-coded paths, model names or thresholds in code — use `Settings`.
- Every prompt is a versioned file under `prompts/` with a version string stored with results.
- Commit messages: `<area>: <change>` (e.g. `extract: add grounding check`).
