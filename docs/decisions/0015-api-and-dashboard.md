# ADR-0015: API and Dashboard Decisions, Findings and Known Gaps

## Status
Accepted. The API and all seven dashboard pages are built and tested; several things could not be verified against live infrastructure (see "Verification status").

## Context
Phase 8 puts a thin FastAPI layer over the pipelines and run store and a Next.js dashboard on top, for judges to see who wins where, at what cost, why pipelines fail, and to ask live questions.

## Decisions that differ from the phase plan
1. **`dashboard/`, not `frontend/`**, and `server/api/`, not `src/interlock/api/`: the repository already uses these names.
2. **Next.js 16 and Tailwind 4** (what the repo's app was created with), not 14. The repo's `AGENTS.md` warns its conventions differ from older releases, so the bundled docs were read first. One consequence: an error boundary's recovery prop is `retry` here (older releases: `reset`).
3. **Run-store reads reuse the eval harness** (`summarize`, `compare_runs`), so a number on the dashboard cannot differ from `hl eval` / `hl compare`.
4. **Leaders are only called "clear" when the paired-difference interval excludes 0**, and a tie for first names the tied pipelines. The plan's "where each wins" table asked for exactly this; ties needed their own representation.
5. **Extra routes the plan implies but does not list**: `GET /review-queue` (read-only; the plan lists the page but no route), `GET /documents/{id}/pages/{n}` and `GET /documents/{id}/pdf` (the citation drawer must show "original excerpt and PDF page link"), and `GET /examples` (preset chips).
6. **The subgraph canvas is a small deterministic SVG layout, not React Flow / Cytoscape.** It avoids a heavy dependency, needs no physics, always draws the same graph, and is unit-tested. `@tanstack/react-table` was not needed: the failure table's filtering is a tested pure function.
7. **The demo cache is built only from stored runs** (`hl demo-cache`) and never written by hand; failed answers (`status=error`) are excluded, and a pipeline with no stored answer is absent from a line and shown as "No stored answer" rather than invented.
8. **Gold answers are served for the dev split always and for test only with `include_gold=true`**, and the inspector fetches gold only when "Show gold answer" is on.
9. **Read-only routes are cached for 15 s** (`READ_CACHE_SECONDS`, 0 disables), and only successes are kept, so a 404 for a run that is still finishing is never cached.

## Findings worth knowing
- **The run store is a remote Turso database**, so every query costs a network round trip (about 0.3-1.3 s). The first version of the API issued many small queries per request and pages took 4-12 s. Counting data-quality figures in one query (6.4 s to 1.5 s), loading a run's scores, answers and categories in one query, and the read cache brought cold requests to 0.7-2.2 s and repeats to about a millisecond. Pages are still not instant on a cold cache; a local database or a longer cache TTL would help.
- **Provenance is measured, not assumed: 28.2% of accepted facts carry a quoted source page** in the local store (the plan's overview card assumed 100%). The manually entered board records have no evidence block, so they cannot be cited to a page. The dashboard shows the measured number with a "below 100%" flag.
- **The model does not always write inline `[E#]` markers.** Structured citations are therefore always shown as their own row of chips, so they are reachable whether or not the text contains markers.
- **A browser run caught defects unit tests could not**: unreachable citations (above), the slow pages (above), and a default argument bound at definition time that made a timeout un-configurable (fixed in `live.py` and `documents.py`).

## Verification status
- **Backend**: 782 Python tests pass (unit and TestClient integration): every route, input validation, per-pipeline failure isolation, per-pipeline timeouts, demo mode with no key, CORS (allowed and refused origins), JSON 500s that still carry CORS headers, the cache, and path-traversal attempts on the document routes.
- **Frontend**: 55 Vitest tests (API client failure handling, run selection, chart data, failure filtering, graph layout, question checks) plus a typecheck, ESLint and a production build.
- **Browser**: `dashboard/e2e/smoke.mjs` (30 checks) drives all seven pages in Chromium against the real API and the real run store; `dashboard/e2e/graph.mjs` (15 checks) drives the subgraph canvas against `tests/e2e/fixture_server.py`.
- **Not verified live**: `subgraph_by_edges.gsql` has never been installed or run (the cluster has no graph, and `.env`'s `TG_GRAPH` names one that does not exist on it); the canvas was exercised with a stubbed query result of the same shape. A live `/compare` through the real pipelines was not run (the free-tier daily token limit was exhausted earlier in the project), so the live path is covered by fake pipelines. The PDF and parsed-page routes return clean 404s here because `data/raw` and `data/parsed` are not in this checkout; they are tested with temporary files.
- **Exit criteria**: 1 (five pages load and render data from the API) and 3 (demo mode with no key) are met and browser-verified. 4 (API integration tests) is met. 2 (inspector shows a side-by-side comparison with an interactive graph on a multi-hop question) is met against the fixture, not against a real graph run, because none exists yet.
- **Content caveat**: with the data that exists today (5 dev questions, a RAG run and a text-only agent run, no GraphRAG run) the dashboard demonstrates the machinery, not a result: every chart carries a small-sample warning, and the GraphRAG column is empty.

## Consequences
- Phase 9 packages the API, dashboard and graph database together. The dashboard reads `NEXT_PUBLIC_API_URL` (inlined at build time) and the API allows the origins in `CORS_ORIGINS`.
- Once a graph run exists, rebuild the cache with `hl demo-cache --rag ... --graphrag ... --agent ...` and install `subgraph_by_edges` with `hl build-graph --from schema`.
