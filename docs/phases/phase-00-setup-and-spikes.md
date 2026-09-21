# Phase 0 — Environment Setup, LLM Gateway, and Parser Spike

> **Accuracy note.** Code blocks are sketches showing structure and intent. Check every library call against current official docs before using it. Items marked **Verify** are ones I am not fully certain about.

---

## 0.1 Overview

| Item | Detail |
| --- | --- |
| Goal | A working development environment, a running Neo4j, a settings system, a run store, an LLM gateway that caches/logs/costs every call, and an evidence-based PDF parser choice |
| Why | Every later phase depends on these. The gateway makes all LLM work cheap to repeat and fair to compare. The parser spike prevents discovering in Phase 2 that your parser breaks the tables you need |
| Prerequisites | A laptop with Git, Docker Desktop (or Docker Engine + Compose), Python 3.11+, an LLM API key |
| Produces | Repo skeleton, `Settings`, SQLite migrations, `LLMGateway`, Neo4j connectivity, ADR-0001 (parser), answers to open questions Q-01–Q-04 |
| PRD links | NFR-02, NFR-05, NFR-06, NFR-07 |
| TRD links | §1, §2, §3, §5, §7.1, §11 |

---

## 0.2 Concepts you will learn in this phase

### Reproducible Python environments
A **lockfile** (`uv.lock`) records the exact version of every dependency. Anyone who runs `uv sync` gets the same versions, so "works on my machine" problems disappear. You add a dependency with `uv add <pkg>`, which updates both `pyproject.toml` and the lockfile. **Verify** current uv commands in its docs.

### Configuration vs secrets
- **Configuration** (thresholds, model names, file paths) is safe to commit. It lives in YAML.
- **Secrets** (API keys, passwords) must never be committed. They live in `.env`, which is gitignored. A committed `.env.example` lists the variable names with empty values.
- A single typed `Settings` object merges both, so code never reads environment variables directly.

### Content-addressed caching
Instead of naming a cache entry by *when* it was made, name it by a hash of *what went in*: model name + messages + parameters. The same input always hits the same cache file. Consequences:
- Rerunning an evaluation costs nothing if nothing changed.
- Changing a prompt changes the hash, so you get a fresh call automatically.
- CI can run with the cache and no API key.

### Retries with exponential backoff and jitter
When a provider returns "rate limited" (HTTP 429) or a server error (5xx), wait and retry. Each wait doubles (1 s, 2 s, 4 s…) and adds a small random amount (jitter) so many requests do not retry at the same instant. Give up after a fixed number of tries and raise a clear error.

### Cost accounting
Providers bill per input and output token. The gateway reads token counts from each response, multiplies by the per-million-token price from `models.yaml`, and adds to a running total. A **spend cap** stops everything if the total passes your budget.

### Decision records (ADRs)
A short file recording a decision, the alternatives and the reason. It stops you re-arguing settled questions and shows judges disciplined engineering.

---

## 0.3 Directory layout created in this phase

```
interlock/
├── pyproject.toml
├── uv.lock
├── Makefile
├── docker-compose.yml
├── .env.example
├── .gitignore
├── config/
│   ├── models.yaml
│   └── pipeline.yaml
├── data/
│   ├── raw/.gitkeep
│   ├── inbox/.gitkeep
│   ├── parsed/.gitkeep
│   └── cache/llm/.gitkeep
├── db/.gitkeep
├── src/interlock/
│   ├── __init__.py
│   ├── settings.py
│   ├── cli.py
│   ├── common/
│   │   ├── __init__.py
│   │   ├── logging.py
│   │   ├── ids.py
│   │   └── timing.py
│   ├── store/
│   │   ├── __init__.py
│   │   ├── db.py
│   │   └── migrations/0001_init.sql
│   ├── graph/
│   │   ├── __init__.py
│   │   └── client.py
│   └── llm/
│       ├── __init__.py
│       ├── models.py
│       ├── cache.py
│       ├── pricing.py
│       ├── gateway.py
│       └── providers/
│           ├── __init__.py
│           ├── base.py
│           └── <your_provider>.py
├── spikes/
│   └── parser_bakeoff.py
├── tests/
│   ├── unit/
│   │   ├── test_cache.py
│   │   ├── test_gateway.py
│   │   └── test_settings.py
│   └── integration/
│       └── test_neo4j_connect.py
└── docs/
    └── decisions/0001-pdf-parser.md
```

---

## 0.4 Step-by-step implementation

### Step 1 — Create the repository

1. Create an empty GitHub repository `interlock` (public, so CI minutes are free; **Verify** current GitHub Actions free-tier terms).
2. Clone it locally.
3. Create `.gitignore` **before the first commit**:

```
# secrets
.env
# data (large / regenerable)
data/raw/
data/parsed/
data/extracted/
data/cache/
db/*.sqlite
# python
__pycache__/
.venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
# os/editor
.DS_Store
.idea/
.vscode/
```

4. Add a `LICENSE` (MIT is common for hackathons; check organizer rules).

**Verify it worked:** `git status` shows `.gitignore` and `LICENSE` only.

### Step 2 — Python project with uv

1. Install uv (**Verify** the install command on uv's docs).
2. Initialize a package project and pin Python:
   - `uv init --package` (or the current equivalent; **Verify**).
   - Set `requires-python = ">=3.11"` in `pyproject.toml`.
3. Add runtime dependencies (names are real packages; **Verify** versions at install time):
   - `pydantic`, `pydantic-settings`, `pyyaml`, `httpx`, `neo4j`, `pymupdf`, `pdfplumber`, `rapidfuzz`, and your LLM provider's SDK.
4. Add dev dependencies: `pytest`, `ruff`, `mypy`.
5. Configure Ruff and mypy in `pyproject.toml`:

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM"]

[tool.mypy]
python_version = "3.11"
strict = false
warn_unused_ignores = true
disallow_untyped_defs = true
packages = ["interlock"]
```

**Verify it worked:** `uv run python -c "import pydantic, neo4j, fitz, pdfplumber"` exits without error. (PyMuPDF's import name has historically been `fitz`, and newer versions also offer `pymupdf`; **Verify**.)

### Step 3 — Makefile

```make
.PHONY: setup lint type test up down

setup:
	uv sync

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

type:
	uv run mypy src

test:
	uv run pytest -q

up:
	docker compose up -d neo4j

down:
	docker compose down
```

On Windows without `make`, use the same commands directly or install make via your package manager.

### Step 4 — Neo4j in Docker Compose

```yaml
services:
  neo4j:
    image: neo4j:5-community        # Verify current tag
    ports:
      - "7474:7474"                 # browser UI
      - "7687:7687"                 # bolt protocol
    environment:
      NEO4J_AUTH: "neo4j/${NEO4J_PASSWORD}"
      # Memory settings: env var names follow Neo4j's convention of
      # replacing dots with underscores and doubling existing underscores. Verify.
      NEO4J_server_memory_heap_initial__size: "1G"
      NEO4J_server_memory_heap_max__size: "1G"
      NEO4J_server_memory_pagecache_size: "1G"
    volumes:
      - neo4j_data:/data
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:7474 || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 10
volumes:
  neo4j_data:
```

1. `cp .env.example .env`, set `NEO4J_PASSWORD`.
2. `make up`.
3. Open `http://localhost:7474`, log in, run `RETURN 1`.
4. Check the version: run `CALL dbms.components()` in the browser. Confirm it is a 5.x version that supports vector indexes. **Verify** the minimum version in Neo4j's vector index docs.

### Step 5 — Settings

`src/interlock/settings.py`:

```python
from pathlib import Path
import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]

class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    llm_provider: str = "anthropic"
    llm_api_key: str = ""
    judge_api_key: str = ""
    embedding_api_key: str = ""
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    sqlite_path: str = "db/interlock.sqlite"
    llm_spend_cap_usd: float = 25.0
    log_level: str = "INFO"

class ModelRole(BaseModel):
    provider: str
    model: str
    temperature: float = 0.0
    max_output_tokens: int = 1500

class Price(BaseModel):
    input: float
    output: float

class ModelsConfig(BaseModel):
    extractor: ModelRole
    answerer: ModelRole
    judge: ModelRole
    helper: ModelRole
    embedding: dict
    pricing_usd_per_million_tokens: dict[str, Price]

class Settings(BaseModel):
    secrets: Secrets
    models: ModelsConfig
    pipeline: dict
    root: Path = ROOT

def load_settings() -> Settings:
    models = ModelsConfig(**yaml.safe_load((ROOT / "config/models.yaml").read_text()))
    pipeline = yaml.safe_load((ROOT / "config/pipeline.yaml").read_text())
    return Settings(secrets=Secrets(), models=models, pipeline=pipeline)
```

Why typed: a typo in `models.yaml` fails at startup with a clear message, not deep inside an evaluation run.

Fill `config/models.yaml` and `config/pipeline.yaml` from TRD §3.2 and §3.3. Leave model names as placeholders until you pick them from the provider's current model list.

### Step 6 — Logging and IDs

`common/logging.py` — JSON lines to stdout:

```python
import json, logging, sys, time

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "component": record.name,
            "event": record.getMessage(),
        }
        extra = getattr(record, "details", None)
        if extra:
            payload["details"] = extra
        return json.dumps(payload, ensure_ascii=False)

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(JsonFormatter())
        logger.addHandler(h)
        logger.setLevel(logging.INFO)
    return logger
```

Usage: `log.info("llm_call", extra={"details": {...}})`.

`common/ids.py`:

```python
import hashlib, uuid

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def sha256_text(s: str) -> str:
    return sha256_bytes(s.encode("utf-8"))

def new_request_id() -> str:
    return uuid.uuid4().hex[:16]
```

`common/timing.py` — a context manager that measures milliseconds:

```python
import time
from contextlib import contextmanager

@contextmanager
def timer():
    t = {"ms": 0}
    start = time.perf_counter()
    try:
        yield t
    finally:
        t["ms"] = int((time.perf_counter() - start) * 1000)
```

### Step 7 — Run store with migrations

1. Put the full schema from TRD §5 in `store/migrations/0001_init.sql`.
2. `store/db.py`:

```python
import sqlite3
from pathlib import Path

MIGRATIONS = Path(__file__).parent / "migrations"

def connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")      # better concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def migrate(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
    applied = {r[0] for r in conn.execute("SELECT version FROM schema_version")}
    for f in sorted(MIGRATIONS.glob("*.sql")):
        v = int(f.name.split("_")[0])
        if v not in applied:
            conn.executescript(f.read_text())
            conn.execute("INSERT INTO schema_version(version) VALUES (?)", (v,))
            conn.commit()
```

Why migrations: when you add a column in Phase 5, you add `0002_*.sql` instead of deleting your database.

**Verify it worked:** `uv run python -c "from interlock.store.db import connect, migrate; c=connect('db/interlock.sqlite'); migrate(c)"` then open the file with any SQLite viewer and see the tables.

### Step 8 — Neo4j client

`graph/client.py`:

```python
from neo4j import GraphDatabase, Driver

_driver: Driver | None = None

def get_driver(uri: str, user: str, password: str) -> Driver:
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(uri, auth=(user, password))
        _driver.verify_connectivity()      # Verify method name in current driver docs
    return _driver

def run_read(driver: Driver, cypher: str, **params) -> list[dict]:
    def _tx(tx):
        return [r.data() for r in tx.run(cypher, **params)]
    with driver.session() as s:
        return s.execute_read(_tx)         # Verify

def run_write(driver: Driver, cypher: str, **params) -> None:
    def _tx(tx):
        tx.run(cypher, **params).consume()
    with driver.session() as s:
        s.execute_write(_tx)               # Verify
```

**Verify it worked:** `run_read(driver, "RETURN 1 AS x") == [{"x": 1}]`.

### Step 9 — LLM gateway

This is the most important component of this phase.

#### 9a. Models (`llm/models.py`)
Copy `Message`, `ToolSpec`, `LLMRequest`, `ToolCall`, `LLMResponse` from TRD §7.1.

#### 9b. Cache (`llm/cache.py`)

```python
import json
from pathlib import Path
from interlock.common.ids import sha256_text

class DiskCache:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def key(self, model: str, payload: dict) -> str:
        # sort_keys makes the hash stable regardless of dict order
        return sha256_text(json.dumps({"model": model, **payload}, sort_keys=True))

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"   # shard to avoid huge folders

    def get(self, key: str) -> dict | None:
        p = self._path(key)
        return json.loads(p.read_text()) if p.exists() else None

    def put(self, key: str, value: dict) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False))
        tmp.replace(p)                        # atomic on the same filesystem
```

What goes in the payload: messages, tools, response schema, temperature, max output tokens. **Not** the request_id (that would defeat caching).

#### 9c. Pricing (`llm/pricing.py`)

```python
def cost_usd(prices: dict, model: str, tokens_in: int, tokens_out: int) -> float:
    p = prices.get(model)
    if p is None:
        return 0.0          # log a warning: unknown price means cap cannot protect you
    return (tokens_in * p.input + tokens_out * p.output) / 1_000_000
```

#### 9d. Provider adapter (`llm/providers/base.py` + one implementation)

```python
from typing import Protocol
from interlock.llm.models import LLMRequest, LLMResponse

class Provider(Protocol):
    def call(self, model: str, req: LLMRequest) -> LLMResponse: ...

class RetryableError(Exception): ...
class FatalError(Exception): ...
```

The concrete adapter:
- Converts `Message` and `ToolSpec` into the provider's SDK format.
- Calls the SDK.
- Maps rate-limit/server/timeouts to `RetryableError`; auth/invalid-request to `FatalError`.
- Reads text, tool calls and token usage from the response.

**Verify** in your provider's current SDK docs: the method for creating a message/completion, how tools are passed, how tool calls appear in the response, how usage is reported, and which exception classes indicate rate limits.

Structured output: providers offer JSON-schema-constrained output or tool calling with a schema. A portable approach is to define a single tool whose parameters are your schema and require the model to call it. **Verify** your provider's recommended approach.

#### 9e. Gateway (`llm/gateway.py`)

```python
import random, time
from interlock.llm.cache import DiskCache
from interlock.llm.models import LLMRequest, LLMResponse
from interlock.llm.pricing import cost_usd
from interlock.llm.providers.base import RetryableError

class SpendCapExceeded(Exception): ...

class LLMGateway:
    def __init__(self, settings, providers: dict, cache: DiskCache, store, logger,
                 max_retries: int = 5, offline: bool = False):
        self.s, self.providers, self.cache = settings, providers, cache
        self.store, self.log, self.max_retries = store, logger, max_retries
        self.offline = offline            # CI mode: cache only
        self.spent = 0.0

    def complete(self, req: LLMRequest, request_id: str | None = None) -> LLMResponse:
        role = getattr(self.s.models, req.role)
        payload = req.model_dump(exclude={"role"})
        payload["temperature"] = req.temperature
        key = self.cache.key(role.model, payload)

        hit = self.cache.get(key)
        if hit is not None:
            resp = LLMResponse(**hit, cache_hit=True)
            self._record(key, req.role, role, resp, None)
            return resp
        if self.offline:
            raise RuntimeError(f"cache miss in offline mode: {key}")

        if self.spent >= self.s.secrets.llm_spend_cap_usd:
            raise SpendCapExceeded(f"spent ${self.spent:.2f}")

        provider = self.providers[role.provider]
        delay = 1.0
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = provider.call(role.model, req)
                break
            except RetryableError as e:
                if attempt == self.max_retries:
                    self._record(key, req.role, role, None, str(e))
                    raise
                time.sleep(delay + random.uniform(0, delay / 2))
                delay *= 2

        resp.cost_usd = cost_usd(self.s.models.pricing_usd_per_million_tokens,
                                 role.model, resp.tokens_in, resp.tokens_out)
        self.spent += resp.cost_usd
        self.cache.put(key, resp.model_dump(exclude={"cache_hit"}))
        self._record(key, req.role, role, resp, None)
        return resp

    def _record(self, key, role_name, role, resp, error):
        # insert a row into llm_calls; log one JSON line
        ...
```

Design notes:
- `offline=True` is used in CI and tests: any cache miss is an error, so tests never spend money.
- The spend counter should also be persisted (sum of `llm_calls.cost_usd`) so it survives restarts. Load it at startup.
- Temperature 0 reduces randomness but some providers are still not fully deterministic; the cache makes reruns identical anyway.

**Verify it worked:**
1. Make one real call through a tiny CLI command, e.g. `uv run hl llm-ping "Say OK"`.
2. Check a JSON log line and a new `llm_calls` row with tokens and cost.
3. Run it again: `cache_hit=1`, cost 0.

### Step 10 — CLI skeleton

Use the standard library `argparse` (no extra dependency) or a CLI library of your choice. Commands you will add over time:

| Command | Phase |
| --- | --- |
| `hl llm-ping "<text>"` | 0 |
| `hl db-migrate` | 0 |
| `hl fetch`, `hl ingest-inbox`, `hl coverage` | 1 |
| `hl parse`, `hl extract`, `hl review` | 2 |
| `hl resolve`, `hl load`, `hl embed`, `hl build-graph` | 3 |
| `hl ask --pipeline <p> "<q>"` | 4 |
| `hl eval --pipeline <p> --split <s>` | 5 |

Register the entry point in `pyproject.toml` under `[project.scripts]` as `hl = "interlock.cli:main"`.

### Step 11 — PDF parser bake-off

Goal: pick the parser using evidence from **your** documents.

1. Manually download 5 annual reports: different companies, different years, at least one with complex tables.
2. For each report, find the page ranges of the corporate governance report (board composition table) and the related-party transactions note. Write them in `spikes/pages.yaml`.
3. `spikes/parser_bakeoff.py` extracts those pages with each candidate:

```python
import fitz           # PyMuPDF; Verify import name for your version
import pdfplumber

def pymupdf_text(path, pages):
    doc = fitz.open(path)
    return {p: doc[p - 1].get_text("text") for p in pages}   # 0-based index

def pymupdf_tables(path, pages):
    doc = fitz.open(path)
    out = {}
    for p in pages:
        # find_tables exists in newer PyMuPDF versions; Verify
        tabs = doc[p - 1].find_tables()
        out[p] = [t.extract() for t in tabs]
    return out

def plumber(path, pages):
    out = {}
    with pdfplumber.open(path) as pdf:
        for p in pages:
            page = pdf.pages[p - 1]
            out[p] = {"text": page.extract_text() or "", "tables": page.extract_tables()}
    return out
```

Optionally add one layout-aware parser (e.g. Docling). **Verify** its current API.

4. Score each parser on each target page (1–5):

| Criterion | What to check |
| --- | --- |
| Reading order | Paragraphs in the right order, columns not interleaved |
| Table structure | Director names aligned with their category and meeting attendance; amounts aligned with counterparties |
| Numbers | No merged digits, correct decimal points, units visible |
| Page numbers | Page index matches the PDF viewer's page |
| Speed | Seconds per 100 pages |

5. Record results in `docs/decisions/0001-pdf-parser.md`. A common outcome is "PyMuPDF for text, pdfplumber for tables", but decide from your scores.

### Step 12 — Resolve open questions

| Question | How to resolve | Where to record |
| --- | --- | --- |
| Q-01 Dataset given? | Read the hackathon brief, FAQ, Discord/announcements | `docs/decisions/0000-scope.md` |
| Q-02 Paid APIs + budget | Rules + team budget; set `LLM_SPEND_CAP_USD` | same |
| Q-03 Download allowed? | Read terms of use and robots.txt of each source site | same |
| Q-04 DINs available? | Search your 5 sample reports for 8-digit director IDs in the governance report | same |

---

## 0.5 Tests for this phase

| Test | File | What it proves |
| --- | --- | --- |
| Cache key stable under dict reordering | `test_cache.py` | Same input → same key |
| Cache key changes when temperature changes | `test_cache.py` | Config changes invalidate |
| put/get round trip; atomic write leaves no `.tmp` | `test_cache.py` | Cache integrity |
| Gateway returns cached response without calling provider | `test_gateway.py` | Use a fake provider that raises if called |
| Gateway retries on `RetryableError` then succeeds | `test_gateway.py` | Fake provider fails twice then succeeds; monkeypatch `time.sleep` |
| Gateway gives up after max retries | `test_gateway.py` | Raises after N attempts |
| Spend cap raises | `test_gateway.py` | Set cap 0.0; first uncached call raises |
| Offline mode raises on miss | `test_gateway.py` | CI safety |
| Settings load fails on bad YAML | `test_settings.py` | Fail fast |
| Neo4j connectivity | `test_neo4j_connect.py` | Marked integration; skipped if Neo4j not up |

Fake provider example:

```python
class FakeProvider:
    def __init__(self, fail_times=0):
        self.calls = 0; self.fail_times = fail_times
    def call(self, model, req):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RetryableError("429")
        return LLMResponse(text="OK", tool_calls=[], tokens_in=10, tokens_out=2,
                           cost_usd=0, latency_ms=5, cache_hit=False, model=model)
```

---

## 0.6 Error handling introduced

| Situation | Behavior |
| --- | --- |
| Missing `.env` value | `Settings` fails at startup with the variable name |
| Neo4j down | `get_driver` raises with URI in the message; CLI prints "run `make up`" |
| Provider rate limit | Retries with backoff |
| Invalid API key | `FatalError`, no retry, clear message |
| Spend cap reached | `SpendCapExceeded`; batch commands stop cleanly |

---

## 0.7 Exit criteria

| # | Criterion | How to check |
| --- | --- | --- |
| 1 | `make setup lint type test` passes | Run it |
| 2 | Neo4j reachable from Python | `run_read(..., "RETURN 1")` |
| 3 | One real LLM call logged with tokens and cost | `llm_calls` row |
| 4 | Second identical call is a cache hit with zero cost | `cache_hit=1` |
| 5 | Parser chosen with a written ADR | `docs/decisions/0001-pdf-parser.md` |
| 6 | Q-01 to Q-04 answered or explicitly assumed | `docs/decisions/0000-scope.md` |
| 7 | No secrets in git history | `git log -p | grep -i key` shows nothing sensitive |

---

## 0.8 Pitfalls and debugging

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Cache never hits | Request ID or timestamp included in the hashed payload | Hash only model + content + params |
| Cached answer returned after changing model | Model name missing from key | Include model in key |
| Neo4j container restarts repeatedly | Too much memory configured | Lower heap/page cache |
| `ImportError: fitz` | Different PyMuPDF import name or a conflicting package named `fitz` | Check PyMuPDF docs; uninstall the unrelated `fitz` package if present |
| Cost always 0 | Model name in `pricing` doesn't exactly match the model string | Copy the exact string |
| Committed `.env` by mistake | `.gitignore` added too late | Rotate the key immediately; remove from history |

---

## 0.9 Hand-off to Phase 1

Phase 1 needs: `Settings`, SQLite with `documents` and `fetch_attempts` tables, logging, `sha256_bytes`, and the CLI entry point. All are now in place.
