# Phase 9 — Hardening: Tests, Packaging, CI and Documentation

> **Accuracy note.** Dockerfile, Compose and GitHub Actions snippets are sketches; verify image tags, action versions and syntax against current docs.

---

## 9.1 Overview

| Item | Detail |
| --- | --- |
| Goal | A reproducible, tested, documented project that starts with one command on a clean machine and shows its results honestly |
| Why | Judges clone the repo. If it doesn't start, most of your work is invisible |
| Prerequisites | Phase 8 complete |
| Produces | Dockerfile, final `docker-compose.yml`, sample-graph auto-import, CI workflow, complete test suite, final README, architecture diagram image, `docs/` complete |
| PRD links | NFR-02, NFR-05, NFR-09, NFR-11; G-6 |
| TRD links | §2, §10, §12, §13 |

---

## 9.2 Concepts you will learn

### Reproducible environments
A container image packages your code with exact dependencies. Compose starts several containers (Neo4j, API, dashboard) with the right network, volumes and environment. The same command works on any machine with Docker.

### Seeding data
The demo needs a graph. Instead of asking judges to run extraction (needs API keys, time and money), ship a small sample graph and import it automatically on first start.

### Continuous integration
Every push runs lint, type checks and tests on a clean machine. It catches "works on my machine" problems early and shows judges the project is maintained. Tests use cached LLM responses, so CI needs no API key and costs nothing.

### Writing for readers in a hurry
A README is read in under 2 minutes. Order: what it is → headline result → how to run → how it works → limitations.

---

## 9.3 Files created or finalized

```
Dockerfile
docker-compose.yml
.dockerignore
scripts/
├── seed_graph.py         # import data/samples/graph/*.jsonl if graph is empty
└── entrypoint.sh         # wait for Neo4j, seed, start service
.github/workflows/ci.yml
README.md
docs/
├── PRD.md  TRD.md  ARCHITECTURE.md
├── phases/
├── decisions/
├── data-quality.md
├── evaluation.md
├── results.md             # final numbers with run ids
└── architecture.png       # exported diagram
tests/                     # gaps filled
```

---

## 9.4 Step-by-step implementation

### Step 1 — Fill test gaps

Walk through TRD §12 and every phase's test table. Make a checklist in `docs/test-plan.md` with status per test. Typical gaps at this point:
- Security tests (guardrails, calculator, prompt injection) — must be complete.
- Contract tests: every pipeline returns a valid `AnswerResult` on every question in the 10-question smoke set.
- Runner resume and offline tests.
- API tests.

Mark integration tests with a pytest marker (e.g. `@pytest.mark.integration`) so unit tests run fast by default: `pytest -m "not integration"`.

### Step 2 — Smoke evaluation fixture

1. Select 10 dev questions (2 per main category).
2. Run all three pipelines on them once with a real key.
3. Copy the used LLM cache entries into `tests/fixtures/llm_cache/` (committed; small).
4. A test runs the three pipelines on these 10 questions with `offline=True` against the **sample graph** and asserts:
    - All results valid.
    - Accuracy per pipeline is within a tolerance of stored reference values (catches regressions).

Important: the sample graph must contain everything these 10 questions need.

### Step 3 — Dockerfile

```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# system deps (add tesseract-ocr only if you use OCR)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# install uv (Verify recommended method in uv docs)
RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev          # Verify flags

COPY src ./src
COPY dashboard ./dashboard
COPY config ./config
COPY scripts ./scripts
COPY data/samples ./data/samples

RUN useradd -m app && chown -R app /app
USER app

ENTRYPOINT ["bash", "scripts/entrypoint.sh"]
```

`.dockerignore`: `.git`, `.venv`, `data/raw`, `data/parsed`, `data/cache`, `db/*.sqlite`, `__pycache__`, `.env`.

Local embedding model: if you use a local embedding model, the API container must load it at startup. Either download it during the image build (larger image, offline-safe) or on first start into a mounted cache volume. Document the choice; the first start may be slow.

### Step 4 — Compose (final)

```yaml
services:
  neo4j:
    image: neo4j:5-community            # Verify tag; pin a specific version for reproducibility
    environment:
      NEO4J_AUTH: "neo4j/${NEO4J_PASSWORD:-demo-password}"
      NEO4J_server_memory_heap_max__size: "1G"      # Verify env var naming
      NEO4J_server_memory_pagecache_size: "1G"
    ports: ["7474:7474", "7687:7687"]
    volumes: ["neo4j_data:/data"]
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:7474 || exit 1"]
      interval: 10s
      retries: 20

  api:
    build: .
    command: ["api"]
    env_file: [.env]
    environment:
      NEO4J_URI: "bolt://neo4j:7687"
      DEMO_MODE: "${DEMO_MODE:-true}"
    ports: ["127.0.0.1:8000:8000"]
    volumes: ["./db:/app/db"]
    depends_on:
      neo4j: {condition: service_healthy}

  dashboard:
    build: .
    command: ["dashboard"]
    environment:
      API_URL: "http://api:8000"
    ports: ["127.0.0.1:8501:8501"]
    depends_on: [api]

volumes:
  neo4j_data:
```

Make `.env` optional for the demo: provide defaults so `docker compose up` works with no `.env` in demo mode (and document how to add a key for live questions).

### Step 5 — Entrypoint and seeding

`scripts/entrypoint.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
case "${1:-api}" in
  api)
    uv run python scripts/seed_graph.py          # no-op if graph not empty
    uv run python -m interlock.cli db-migrate
    uv run python -m interlock.cli seed-runs   # import sample run results if run store empty
    exec uv run uvicorn interlock.api.main:app --host 0.0.0.0 --port 8000
    ;;
  dashboard)
    exec uv run streamlit run dashboard/app.py --server.port 8501 --server.address 0.0.0.0
    ;;
  *) exec "$@" ;;
esac
```

`scripts/seed_graph.py`:
1. Wait for Neo4j (retry `RETURN 1` for up to ~60 s).
2. If `MATCH (n) RETURN count(n)` > 0 → exit.
3. Create constraints and indexes (Phase 3 schema).
4. Import `nodes.jsonl` and `rels.jsonl` in batches (Phase 3 export format).
5. Create the vector index and wait until it is online.

`seed-runs`: import `data/samples/runs/*.jsonl` (the final test runs' results and scores) so the dashboard shows real numbers immediately. These are exports of your final runs — the same run IDs as in `docs/results.md`.

Size check: keep `data/samples/` small enough for Git (tens of MB at most). If embeddings make it too large, include only chunks for sample companies, or store embeddings as float16/base64 and document it.

### Step 6 — CI workflow (`.github/workflows/ci.yml`)

```yaml
name: ci
on:
  push:
  pull_request:

jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4                  # Verify current major versions
      - uses: actions/setup-python@v5
        with: {python-version: "3.11"}
      - run: pip install uv
      - run: uv sync --frozen
      - run: uv run ruff check src tests
      - run: uv run ruff format --check src tests
      - run: uv run mypy src
      - run: uv run pytest -m "not integration" -q

  integration:
    if: github.event_name == 'pull_request' || github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    services:
      neo4j:
        image: neo4j:5-community
        env:
          NEO4J_AUTH: neo4j/ci-password
        ports: ["7687:7687"]
        options: >-
          --health-cmd "wget -qO- http://localhost:7474 || exit 1"
          --health-interval 10s --health-retries 20
    env:
      NEO4J_URI: bolt://localhost:7687
      NEO4J_PASSWORD: ci-password
      LLM_OFFLINE: "true"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.11"}
      - run: pip install uv && uv sync --frozen
      - run: uv run python scripts/seed_graph.py
      - run: uv run pytest -m integration -q
```

Note: the health command runs inside the service container; if `wget` is not available in the Neo4j image, use another check (**Verify**).

Add a CI badge to the README.

### Step 7 — Security review checklist

| Check | How |
| --- | --- |
| No secrets in history | Search history for key patterns; optionally run a secret scanner such as gitleaks (**Verify** usage) |
| `.env` not committed | `git ls-files .env` is empty |
| API bound to localhost in Compose | `127.0.0.1:` prefixes on ports |
| Guardrail tests pass | CI |
| Demo mode default on | Compose default |
| Disclaimer visible | Dashboard sidebar and README |
| Only public data in samples | Review `data/samples/` |

### Step 8 — Final evaluation runs

1. Freeze code: tag `v1.0-eval`.
2. Run all three pipelines on the test set (`hl eval --pipeline … --split test`), clean git tree.
3. Export results to `data/samples/runs/`.
4. Write `docs/results.md`:
    - Run IDs, git tag, models (as configured), prompt versions, question version.
    - Table: category × pipeline accuracy with 95% CI.
    - Paired differences per category (agent vs GraphRAG, GraphRAG vs RAG).
    - Cost and latency per pipeline.
    - Failure label distribution.
    - 3–5 short worked examples (question, what each pipeline did, why).
    - Limitations.

Only report numbers from these runs; the dashboard loads the same runs.

### Step 9 — README

Structure:

```markdown
# Interlock — RAG vs GraphRAG vs Agentic GraphRAG on corporate governance networks

One-sentence description. CI badge.

## Headline result
Small table: category × pipeline accuracy (with CIs) + cost/latency row. Link to docs/results.md.

## Demo
- Screenshot / GIF of the Question inspector.
- Link to the demo video.

## Quick start (demo, no API key needed)
    git clone … && cd interlock
    docker compose up --build
    open http://localhost:8501

## Live questions (needs an LLM API key)
    cp .env.example .env   # add LLM_API_KEY
    DEMO_MODE=false docker compose up

## How it works
- Architecture diagram (docs/architecture.png)
- 3 bullets per pipeline
- Link to ARCHITECTURE.md

## Data
- Sources, selection rule, years, counts
- Data quality summary (extraction precision, resolution precision)
- How to rebuild: `make build-graph` (needs key, time, cost estimate)

## Evaluation
- Categories, gold construction, verification, judge calibration
- Known biases

## Limitations
## Disclaimer (not investment advice; automatic extraction may contain errors)
## Repository layout
## License
```

### Step 10 — Architecture diagram image

1. Combine ARCHITECTURE.md §4.1, §5.1 and §5.5 into one Mermaid diagram (or draw it in a diagram tool using them as reference).
2. Export to PNG/SVG (Mermaid CLI or an online Mermaid editor; **Verify** tooling).
3. Save as `docs/architecture.png`; embed in README; this file is also the submission's architecture diagram.

### Step 11 — Fresh-clone test

On a different machine (a friend's laptop, or a clean cloud VM):
1. Install only Git and Docker.
2. `git clone …`, `docker compose up --build`.
3. Time until the dashboard shows results.
4. Click through all five pages; ask one cached example question.
5. Fix every problem found; repeat until it works without help.

Record the result (machine, time to start, issues fixed) in `docs/test-plan.md`.

### Step 12 — Optional hosting

Only if Q-05 requires it:
1. Small VM with enough RAM for Neo4j + app (see TRD §9).
2. Install Docker; clone; `docker compose up -d`.
3. Put a reverse proxy with HTTPS and basic auth in front of the dashboard; keep API internal.
4. Keep `DEMO_MODE=true`, or set a low spend cap if live questions are allowed.

---

## 9.5 Exit criteria

| # | Criterion | How to check |
| --- | --- | --- |
| 1 | Fresh clone → `docker compose up` → working dashboard on a second machine | Fresh-clone record |
| 2 | CI green on main | GitHub Actions |
| 3 | Final test runs frozen and exported; `docs/results.md` complete | Files |
| 4 | README complete with headline result, quick start, limitations, disclaimer | Review |
| 5 | Architecture diagram exported | `docs/architecture.png` |
| 6 | Security checklist complete | `docs/test-plan.md` |

---

## 9.6 Pitfalls

| Symptom | Cause | Fix |
| --- | --- | --- |
| API starts before Neo4j is ready | No health wait | `depends_on` with health condition + retry in seed script |
| Dashboard empty on first start | Runs not seeded | `seed-runs` step |
| Image huge | Raw data or model weights copied | `.dockerignore`; decide on model download strategy |
| CI fails only in CI | Hidden dependency on local files or network | Offline mode; fixtures committed |
| README numbers ≠ dashboard numbers | Different runs | Same run IDs in both |

---

## 9.7 Hand-off to Phase 10

Everything is runnable and documented. Phase 10 records the demo and submits.
