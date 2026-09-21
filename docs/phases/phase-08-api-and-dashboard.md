# Phase 8 — API and Metrics Dashboard

> **Accuracy note.** FastAPI, Streamlit, Plotly and pyvis APIs are sketched from common usage; verify against their current docs (Streamlit in particular changes often).

---

## 8.1 Overview

| Item | Detail |
| --- | --- |
| Goal | A thin, typed API over the pipelines and run store, and a five-page Streamlit dashboard that shows results clearly to judges |
| Why | The dashboard is a required deliverable and the main way judges experience the project |
| Prerequisites | Phase 7 complete — all three pipelines have test runs |
| Produces | `api/` package, `dashboard/` app with 5 pages + review tools, demo mode with cached answers |
| PRD links | FR-35 to FR-40, US-01 to US-04, NFR-08 |
| TRD links | §8 (API), §4.3 |

---

## 8.2 Concepts you will learn

### Thin API layer
The API contains no business logic. It validates input, calls pipelines or queries the run store, and returns typed models. All logic stays in the modules, so the CLI, API and eval runner behave identically.

### Running blocking code concurrently
Pipelines are ordinary (blocking) Python functions. To run three at once in an async web server, run each in a worker thread (`asyncio.to_thread`) and `gather` them. Each pipeline returns an `AnswerResult` even on failure, so one error never breaks the others.

### Dashboard design for judges
- Lead with the answer to "who wins where?".
- Every chart states what it shows, which run, and how many questions.
- Uncertainty is visible (confidence intervals), not hidden.
- Drill-down: from a number to the failing questions to one question's full trace.

### Caching in Streamlit
Streamlit reruns the script on every interaction. Load run data with a cache decorator so each rerun doesn't re-query the database (**Verify** current decorator names, e.g. `st.cache_data` / `st.cache_resource`).

---

## 8.3 Files created

```
src/interlock/api/
├── __init__.py
├── main.py            # app, routes
├── deps.py            # shared context (settings, gateway, driver, pipelines)
└── schemas.py         # request/response models not already in pipelines.models
dashboard/
├── app.py             # landing = Overview
├── data.py            # loaders (API client or direct store access)
├── style.py           # pipeline colors, captions, disclaimer
├── components/
│   ├── answer_card.py
│   ├── trace_table.py
│   ├── subgraph_view.py
│   └── ci_bars.py
└── pages/
    ├── 1_Overview.py
    ├── 2_Trade_offs.py
    ├── 3_Failures.py
    ├── 4_Question_inspector.py
    ├── 5_Live_ask.py
    ├── 98_Data_quality.py
    └── 99_Review_queue.py       # from Phase 2 (dev tool)
tests/integration/test_api.py
tests/unit/test_dashboard_data.py
```

---

## 8.4 API implementation

### Step 1 — Shared context (`api/deps.py`)

Create once at startup: settings, SQLite connection factory (one connection per request/thread — SQLite connections shouldn't be shared across threads by default), Neo4j driver (thread-safe, shared), LLM gateway, embedding model (loaded once), pipelines registry.

Use FastAPI's lifespan hook to build and close these (**Verify** the current lifespan API).

### Step 2 — Routes (`api/main.py`)

```python
import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Interlock API")

class AskIn(BaseModel):
    question: str
    pipeline: str

class CompareIn(BaseModel):
    question: str

@app.get("/health")
def health():
    return {"neo4j": ctx.neo4j_ok(), "sqlite": ctx.sqlite_ok(), "llm_key": bool(ctx.settings.secrets.llm_api_key)}

@app.post("/ask")
def ask(body: AskIn):
    p = ctx.pipelines.get(body.pipeline)
    if p is None:
        raise HTTPException(400, f"unknown pipeline {body.pipeline}")
    validate_question(body.question)
    rid = new_request_id()
    res = p.answer(body.question, rid)
    ctx.store.save_adhoc_result(rid, res)
    return res

@app.post("/compare")
async def compare(body: CompareIn):
    validate_question(body.question)
    rid = new_request_id()
    names = ["rag", "graphrag", "agent"]
    results = await asyncio.gather(*[
        asyncio.to_thread(ctx.pipelines[n].answer, body.question, rid) for n in names
    ])
    out = dict(zip(names, results))
    for r in results:
        ctx.store.save_adhoc_result(rid, r)
    return {"request_id": rid, "results": out}
```

`validate_question`: non-empty, ≤ 500 characters, strip control characters. Return 400 otherwise.

Demo mode (`DEMO_MODE=true` or no LLM key): `/compare` first looks up the question (normalized) in `data/samples/cached_answers.jsonl`; if found, return it with `"cached": true`. If not found and no key, return 503 with a clear message ("Live questions need an API key; try one of the example questions").

Other routes (read-only, from the run store):

| Route | Returns |
| --- | --- |
| `GET /runs` | runs with pipeline, split, question version, started/finished, git commit |
| `GET /runs/{run_id}/metrics` | per-category: mean correct + CI, faithfulness, citation accuracy, evidence recall, abstention, latency p50/p90, cost, steps |
| `GET /runs/{run_id}/results/{qid}` | `AnswerResult` + score row |
| `GET /compare-runs?rag=..&graphrag=..&agent=..` | joined per-question table for the three runs + paired-difference CIs |
| `GET /questions?split=test` | questions (gold included only for dev, or with `include_gold=true` for local use) |
| `GET /graph/subgraph?edge_ids=a,b,c` | nodes + edges for visualization |
| `GET /data-quality` | data quality report numbers |

Subgraph route Cypher:

```cypher
MATCH (s)-[r]->(t) WHERE r.edge_id IN $edge_ids
RETURN coalesce(s.entity_id, s.txn_id, s.order_id) AS sid, labels(s)[0] AS slabel,
       coalesce(s.name, s.nature, s.summary) AS sname,
       type(r) AS rel, properties(r) AS rprops,
       coalesce(t.entity_id, t.txn_id, t.order_id) AS tid, labels(t)[0] AS tlabel,
       coalesce(t.name, t.nature, t.summary) AS tname
```

Security: bind to `127.0.0.1` by default; CORS not needed if Streamlit calls the API server-side. If hosted publicly, put basic auth in front (e.g. via a reverse proxy) and keep demo mode on to control cost.

### Step 3 — Run the API

`uv run uvicorn interlock.api.main:app --reload --port 8000` (**Verify**). Open `/docs` for the auto-generated API docs — useful for judges and for your own testing.

---

## 8.5 Dashboard implementation

### Step 4 — Data layer (`dashboard/data.py`)

All pages load data through this module (API client by default; direct store access if `NO_API=true`). Pages never contain SQL.

```python
import httpx, pandas as pd, streamlit as st

API = "http://localhost:8000"

@st.cache_data(ttl=60)              # Verify decorator
def runs() -> pd.DataFrame:
    return pd.DataFrame(httpx.get(f"{API}/runs", timeout=30).json())

@st.cache_data(ttl=60)
def metrics(run_id: str) -> pd.DataFrame:
    return pd.DataFrame(httpx.get(f"{API}/runs/{run_id}/metrics", timeout=30).json())

@st.cache_data(ttl=60)
def joined(rag: str, graphrag: str, agent: str) -> dict:
    return httpx.get(f"{API}/compare-runs", params={"rag": rag, "graphrag": graphrag, "agent": agent},
                     timeout=60).json()
```

Default run selection: the latest finished **test** run per pipeline on the current question version. A sidebar lets you change runs (useful for showing before/after).

### Step 5 — Style (`dashboard/style.py`)

- Fixed pipeline colors used everywhere (choose three colorblind-friendly colors and never reuse them for anything else).
- Fixed pipeline order: RAG, GraphRAG, Agent.
- Helper `caption(run_ids, n)` → "Test set v1, n=196 questions. Runs: rag=…, graphrag=…, agent=…".
- Disclaimer in the sidebar on every page: "Research demo. Facts are extracted automatically from public filings and may contain errors; verify against the cited source. Not investment advice."

### Step 6 — Page 1: Overview

Layout:
1. **Headline row** (three metric cards, one per pipeline): overall accuracy (with CI), mean cost per question, median latency.
2. **Main chart:** grouped bar chart — x = category, bars = pipelines, y = accuracy, error bars = 95% CI. Plotly `go.Bar` with `error_y` (**Verify**).
3. **"Where each wins" table:** for each category, which pipeline is best and whether the paired difference vs the runner-up is clear (CI excludes 0) — show "clear", "unclear".
4. **Data quality panel:** documents, entities, facts with provenance (100%), extraction precision, resolution precision — with a link to page 98.
5. Caption under each chart.

### Step 7 — Page 2: Trade-offs

1. Scatter: x = mean cost per question, y = accuracy; one point per (pipeline, category); color = pipeline, symbol = category. Hover shows numbers.
2. Scatter: x = median latency, y = accuracy (same encoding).
3. Bar: mean LLM calls and tool calls per pipeline.
4. Short text box: "What you pay for the agent's accuracy" — written by you from the numbers.

### Step 8 — Page 3: Failures

1. Stacked bar: failure labels per pipeline (counts or share of that pipeline's wrong answers).
2. Heatmap: category × failure label for a selected pipeline.
3. Filterable table: qid, category, question, which pipelines failed, labels, correctness per pipeline. Filters: category, pipeline, label, "only questions where pipelines disagree".
4. Row click (or selectbox of qid) → link/button to open it in the Question inspector (pass qid via query params; **Verify** Streamlit query-param API).

### Step 9 — Page 4: Question inspector

The most important demo page.

Layout:
1. Question selector (search box + selectbox), category badge, gold answer (test gold shown here — it's your local demo; you may hide it behind a toggle).
2. Three columns (RAG | GraphRAG | Agent), each an **answer card**:
    - Status badge, correct/incorrect badge, failure label.
    - `answer_short` large; `answer_long` below with [E#] markers.
    - Citations list: doc, page, quote (expandable to show page text with highlight).
    - Usage line: tokens, cost, latency, LLM calls, tool calls.
3. **Evidence tabs** under each column: chunks / triples retrieved (show which ones overlap gold evidence with a marker).
4. **Subgraph view** (GraphRAG and Agent): nodes and edges from `evidence` edge IDs, gold edges highlighted.
5. **Agent trace table:** step, tool, arguments (compact), result summary, tokens, latency; errors in red; verifier verdicts.

Subgraph rendering with pyvis (**Verify** API; render to HTML and embed with Streamlit's HTML component):

```python
from pyvis.network import Network
import streamlit.components.v1 as components

def render_subgraph(nodes, edges, gold_edge_ids):
    net = Network(height="450px", width="100%", directed=True)
    for n in nodes:
        net.add_node(n["id"], label=n["name"][:30], title=n["label"], group=n["label"])
    for e in edges:
        net.add_edge(e["source"], e["target"], label=e["rel"],
                     width=4 if e["edge_id"] in gold_edge_ids else 1)
    html = net.generate_html()            # Verify method name
    components.html(html, height=470)
```

Keep graphs small (≤ 60 nodes shown); show "N more omitted" otherwise.

### Step 10 — Page 5: Live ask

1. Text input + "Ask all three" button.
2. Example-question buttons (these are cached, so they work in demo mode without a key).
3. Calls `/compare`; shows a spinner per column; renders three answer cards (reuse component).
4. Optional (secondary goal SG-3): stream agent steps. Simple approach: show the trace after completion. Streaming requires a streaming API route and incremental UI updates — only do this if time allows.
5. "Save to demo run" button stores the result for later inspection.

### Step 11 — Page 98: Data quality
Render `/data-quality`: document counts, record statuses by reason, extraction precision per type, resolution precision, node/edge counts, MENTIONS coverage.

### Step 12 — Cached demo answers

1. Choose 10–20 showcase questions (including the hero questions for the video).
2. Run `/compare` on each with a key; save results to `data/samples/cached_answers.jsonl` (normalized question → three results).
3. Commit this file. Demo mode uses it.

### Step 13 — Usability test

Give the dashboard to someone who hasn't seen it (a classmate). Ask them to:
1. Tell you which pipeline is best for multi-hop questions and how sure we are.
2. Find a question where the agent failed and say why.
3. Ask their own question.
Time them. Anything taking longer than ~1 minute gets redesigned (usually: clearer captions, fewer controls, better defaults).

---

## 8.6 Tests

| Test | Expectation |
| --- | --- |
| `/health` | 200 with booleans |
| `/ask` unknown pipeline | 400 |
| `/ask` empty or 2,000-char question | 400 |
| `/compare` with one pipeline raising internally | 200; that pipeline's result has `status=error`; others ok |
| `/compare` in demo mode, cached question | Returns cached, no LLM call (offline gateway) |
| `/compare` in demo mode, unknown question, no key | 503 with helpful message |
| `/runs/{id}/metrics` | Numbers match a direct computation from `scores` |
| Subgraph route | Returns only requested edges |
| Dashboard data functions | Given fixture API responses, produce expected DataFrames (test without Streamlit UI) |

Use FastAPI's test client for API tests (**Verify** import path).

---

## 8.7 Exit criteria

| # | Criterion | How to check |
| --- | --- | --- |
| 1 | All five pages work on the latest test runs | Click through |
| 2 | A new person answers the three usability questions within a few minutes | Usability notes |
| 3 | Demo mode works without an LLM key for cached questions | Unset key, try |
| 4 | API tests pass | `make test` |

---

## 8.8 Pitfalls

| Symptom | Cause | Fix |
| --- | --- | --- |
| Dashboard slow on every click | No caching; heavy queries | Cache loaders; precompute metrics in the runner |
| Pages run pipelines on load | Calls in page body | Only Live ask calls pipelines, on button press |
| SQLite "database is locked" | Long writes during reads | WAL mode (Phase 0); short transactions |
| Unreadable graph view | Too many nodes | Cap and filter to evidence + gold edges |
| Numbers differ from README | Different runs selected | Show run IDs everywhere; README links the same IDs |

---

## 8.9 Hand-off to Phase 9

Phase 9 packages everything (Docker, CI, docs) so the dashboard and API start with one command on any machine.
