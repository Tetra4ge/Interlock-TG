# Phase 8 — API and Metrics Dashboard (Next.js)

> **Accuracy note.** FastAPI, Next.js, React, Tailwind CSS, Recharts and React Flow / Cytoscape APIs are sketched from standard modern web usage; verify against their current documentation.

---

## 8.1 Overview

| Item | Detail |
| --- | --- |
| Goal | A thin, typed API over the pipelines and run store, and a five-page Next.js dashboard that shows results clearly to judges |
| Why | The dashboard is a required deliverable and the main interactive way judges experience the project |
| Prerequisites | Phase 7 complete — all three pipelines have test runs |
| Produces | `src/interlock/api/` package, `frontend/` Next.js web app with 5 pages + review tools, demo mode with cached answers |
| PRD links | FR-35 to FR-40, US-01 to US-04, NFR-08 |
| TRD links | §8 (API), §4.3 |

---

## 8.2 Concepts you will learn

### Thin API layer with CORS
The FastAPI backend contains no business logic. It validates input, calls pipelines or queries the run store, and returns typed JSON models. Enable CORS (`CORSMiddleware`) so the Next.js frontend (running on `http://localhost:3000`) can communicate seamlessly.

### Running blocking code concurrently
Pipelines are ordinary (blocking) Python functions. To run three at once in an async web server, run each in a worker thread (`asyncio.to_thread`) and `gather` them. Each pipeline returns an `AnswerResult` even on failure, so one error never breaks the others.

### Dashboard design for judges
- Lead with the answer to "who wins where?".
- Every chart states what it shows, which run, and how many questions.
- Uncertainty is visible (confidence intervals), not hidden.
- Drill-down: from a number to the failing questions to one question's full trace.

### State & Data Fetching in Next.js
Use Next.js React Server Components or client-side fetching (React Query / SWR / `fetch`) to load runs and metrics. Cache API responses where appropriate and keep state cleanly isolated.

---

## 8.3 Files created

```
src/interlock/api/
├── __init__.py
├── main.py            # FastAPI app, CORS middleware, routes
├── deps.py            # shared context (settings, gateway, driver, pipelines)
└── schemas.py         # request/response models not already in pipelines.models

frontend/
├── package.json       # Next.js, React, Tailwind CSS, lucide-react, recharts / react-flow
├── tailwind.config.ts
├── tsconfig.json
├── src/
│   ├── app/
│   │   ├── layout.tsx                # App shell, navigation, disclaimer banner
│   │   ├── page.tsx                  # Page 1: Overview
│   │   ├── tradeoffs/page.tsx        # Page 2: Trade-offs
│   │   ├── failures/page.tsx         # Page 3: Failures
│   │   ├── inspector/page.tsx        # Page 4: Question inspector
│   │   ├── live/page.tsx             # Page 5: Live ask
│   │   ├── data-quality/page.tsx     # Page 98: Data quality
│   │   └── review-queue/page.tsx     # Dev tool: Review queue
│   ├── components/
│   │   ├── AnswerCard.tsx
│   │   ├── TraceTable.tsx
│   │   ├── SubgraphCanvas.tsx        # React Flow / Cytoscape / Vis network graph
│   │   ├── CIBarsChart.tsx           # Recharts bar chart with error bounds
│   │   └── RunSelector.tsx
│   └── lib/
│       ├── api.ts                    # Typed API client
│       └── types.ts                  # TypeScript mirrors of Pydantic models
tests/integration/test_api.py
```

---

## 8.4 API implementation

### Step 1 — Shared context (`api/deps.py`)

Create once at startup: settings, Turso DB connection / client, TigerGraph connection (`pyTigerGraph`; one shared read-only connection/token), LLM gateway, embedding model (loaded once), pipelines registry.

Use FastAPI's lifespan hook to build and close these.

### Step 2 — Routes and CORS (`api/main.py`)

```python
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Interlock API")

# Enable CORS for Next.js frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AskIn(BaseModel):
    question: str
    pipeline: str

class CompareIn(BaseModel):
    question: str

@app.get("/health")
def health():
    return {"tigergraph": ctx.tigergraph_ok(), "turso": ctx.turso_ok(), "llm_key": bool(ctx.settings.secrets.llm_api_key)}

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

Subgraph route: an installed GSQL query `subgraph_by_edges(SET<STRING> edge_ids)`.

```gsql
CREATE QUERY subgraph_by_edges(SET<STRING> edge_ids) FOR GRAPH Interlock SYNTAX v2 {
  // For each fact edge type (DIRECTOR_OF, HOLDS_STAKE, SUBSIDIARY_OF, AUDITED_BY, PARTY_TO, NAMED_IN):
  //   SELECT t FROM AnyVertex:s -(EdgeType:e)- :t WHERE e.edge_id IN edge_ids
  //   and PRINT source id/type/name, edge type, edge attributes, target id/type/name.
}
```

### Step 3 — Run the API

`uv run uvicorn interlock.api.main:app --reload --port 8000`. Auto-generated OpenAPI docs are accessible at `http://localhost:8000/docs`.

---

## 8.5 Next.js Frontend implementation

### Step 4 — Initialize Next.js app (`frontend/`)

Create the Next.js frontend with TypeScript and Tailwind CSS:
```bash
npx create-next-app@latest frontend --typescript --tailwind --app --src-dir --import-alias "@/*"
cd frontend
npm install lucide-react recharts @tanstack/react-table
```

### Step 5 — API client (`frontend/src/lib/api.ts`)

```typescript
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function fetchRuns() {
  const res = await fetch(`${API_URL}/runs`, { next: { revalidate: 60 } });
  if (!res.ok) throw new Error('Failed to fetch runs');
  return res.json();
}

export async function fetchMetrics(runId: string) {
  const res = await fetch(`${API_URL}/runs/${runId}/metrics`, { next: { revalidate: 60 } });
  if (!res.ok) throw new Error('Failed to fetch metrics');
  return res.json();
}

export async function compareQuestion(question: string) {
  const res = await fetch(`${API_URL}/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) throw new Error('Failed to compare question');
  return res.json();
}
```

### Step 6 — Style and Colors (`frontend/tailwind.config.ts`)

- Define distinct, colorblind-friendly colors for the pipelines:
  - RAG: `#3B82F6` (Blue)
  - GraphRAG: `#10B981` (Emerald)
  - Agentic GraphRAG: `#8B5CF6` (Purple)
- Persistent disclaimer banner in the header/footer: "Research demo. Facts are extracted automatically from public filings and may contain errors; verify against the cited source. Not investment advice."

### Step 7 — Page 1: Overview (`frontend/src/app/page.tsx`)

Layout:
1. **Headline metric cards:** overall accuracy (with 95% CI), mean cost per question, and median latency for each of RAG, GraphRAG, and Agentic GraphRAG.
2. **Main chart:** Grouped bar chart comparing category accuracy with error bars for confidence intervals (built with Recharts).
3. **"Where each wins" table:** Which pipeline leads per question category and whether the paired-difference CI excludes 0 ("clear" vs "unclear").
4. **Data quality summary card:** counts of documents, entities, validated facts with provenance (100%), and extraction precision.

### Step 8 — Page 2: Trade-offs (`frontend/src/app/tradeoffs/page.tsx`)

1. Scatter chart: Cost vs. Accuracy per pipeline and category.
2. Scatter chart: Latency vs. Accuracy.
3. Bar chart: Average LLM and tool calls per pipeline.
4. Summary takeaway card explaining the cost/accuracy trade-off.

### Step 9 — Page 3: Failures (`frontend/src/app/failures/page.tsx`)

1. Stacked bar chart: breakdown of failure taxonomies (e.g. `retrieval_miss`, `missed_hop`, `math_error`, `hallucination`) per pipeline.
2. Filterable failure table with search, category filtering, and direct click-through to inspect specific questions.

### Step 10 — Page 4: Question Inspector (`frontend/src/app/inspector/page.tsx`)

The showcase inspection page:
1. Searchable question dropdown/list with gold answer toggle.
2. Three side-by-side **Answer Cards** (RAG | GraphRAG | Agentic GraphRAG):
   - Status badge, Correct/Incorrect tag, Failure reason tag.
   - `answer_short` prominently displayed; `answer_long` with inline citation chips `[E1, p.42]`.
   - Citations modal/drawer showing original excerpt and PDF page link.
   - Resource metrics: token count, cost ($), latency (ms), tool calls.
3. **Interactive Subgraph Canvas (`components/SubgraphCanvas.tsx`):**
   - Renders retrieved knowledge graph nodes and edges using React Flow, Cytoscape.js, or HTML5 Canvas.
   - Highlights gold-standard evidence paths in distinct colors.
4. **Agent Trace Table:** Chronological step-by-step breakdown (planning, GSQL tool calls, calculator, verifier verdicts).

### Step 11 — Page 5: Live Ask (`frontend/src/app/live/page.tsx`)

1. Interactive prompt bar with preset demo question chips (cached for zero-cost instant response).
2. Live compare execution displaying progress spinners across all three pipelines.
3. Renders the resulting 3 answer cards side-by-side.

### Step 12 — Cached Demo Answers

1. Choose 10–20 showcase questions (including video hero questions).
2. Save precomputed results to `data/samples/cached_answers.jsonl`.
3. Commit this file so judges can run the full Next.js UI locally without requiring an API key.

---

## 8.6 Tests

| Test | Expectation |
| --- | --- |
| `/health` | 200 with booleans |
| `/ask` unknown pipeline | 400 |
| `/ask` empty or 2,000-char question | 400 |
| `/compare` with one pipeline raising internally | 200; that pipeline's result has `status=error`; others ok |
| `/compare` in demo mode, cached question | Returns cached, no LLM call |
| `/compare` in demo mode, unknown question, no key | 503 with helpful message |
| `/runs/{id}/metrics` | Numbers match a direct computation from `scores` |
| Subgraph route | Returns only requested edges |
| Frontend API client | Handles error responses gracefully and returns typed data |

---

## 8.7 Exit criteria

| # | Criterion | How to check |
| --- | --- | --- |
| 1 | All five pages in Next.js frontend load and render data from API | Navigate through `http://localhost:3000` |
| 2 | Question inspector shows side-by-side comparison with interactive graph | Test on a multi-hop question |
| 3 | Demo mode works without an LLM key for cached questions | Unset key and execute preset questions |
| 4 | FastAPI integration tests pass | `make test` |

---

## 8.8 Hand-off to Phase 9

Phase 9 packages everything (Docker Compose with API, Next.js frontend, and TigerGraph, CI, docs) so the entire platform starts with one command on any machine.
