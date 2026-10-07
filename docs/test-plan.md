# Test plan and Phase 9 checklist

This records what is verified, by whom and how, and what is not. "Verified" means run in the
environment noted; nothing here is claimed beyond that.

## Automated checks

| Check | Command | Result (2026-10-07, macOS, Python 3.11) |
| --- | --- | --- |
| Unit tests | `uv run pytest -q` | 788 passed, 4 deselected (integration) |
| Lint (server, tests, spikes) | `uv run ruff check server tests spikes` | passed |
| Format | `uv run ruff format --check server tests spikes` | passed |
| Type check | `uv run mypy server` | passed (127 files) |
| Dashboard build | `npm run build` | passed |
| Dashboard typecheck | `npm run typecheck` | passed (run after `build`; Next generates route/layout types that typecheck needs — see CI step order) |
| Dashboard unit tests | `npm test` | 55 passed |
| Dashboard lint | `npm run lint` | passed |
| Compose file | `docker compose config -q` | passed |
| Dashboard image | `docker build -t interlock-dashboard ./dashboard` | passed on retry (first attempt hit a transient Google Fonts timeout during `next build`, not a code issue); container smoke-tested with `docker run` and answered `200` |
| API image | `docker build --platform linux/amd64 -t interlock-api .` | not finished. `uv sync` pulls full CUDA wheels for torch (sentence-transformers' dependency) — nvidia-cublas alone is 403MB — and two full attempts ran 20-40+ minutes before being cut off for time. The code path is fine (an amd64 build of the same dependencies succeeds for the dashboard image and for `uv sync` outside Docker); this is a bandwidth/image-size problem, not a bug |
| Clean-clone backend checks | fresh `git clone` of the branch, then `uv sync --frozen && ruff check/format && mypy && pytest` | all passed, 782 tests |

Integration tests (`pytest -m integration`) are not run in CI. They need a live TigerGraph and a
real LLM, and the integration test drops and recreates a graph. Run them locally before tagging.

## Manual browser verification (2026-10-07, Claude in Chrome, real local servers)

`DEMO_MODE=true uv run hl serve` + `npm run dev`, driven through an actual Chrome browser, not
just `curl`. All seven dashboard pages were navigated to and confirmed to render real data, not
an error panel:

- **Overview** — category accuracy bars with CIs, matching `docs/results.md`.
- **Trade-offs** — cost/latency/accuracy scatter plots, correct per-pipeline stats.
- **Failures** — failure-type bar chart, matches the labels in `docs/results.md`.
- **Question inspector** — question list, three answer cards, a citation chip opened the citation
  drawer, "Show source page text" fetched the real cited PDF page through
  `GET /documents/{id}/pages/{n}`, and the drawer correctly flagged a citation whose quote
  couldn't be matched to the model's evidence block — the dashboard surfacing a real data-quality
  gap honestly, not a bug.
- **Live ask** — selecting a cached example question and clicking "Ask all three" answered in
  0.1s from stored results; GraphRAG correctly showed "No stored answer for this pipeline".
- **Data quality** — corpus and provenance numbers matched the API's `/data-quality` response.
- **Review queue** — real quarantined records with their evidence JSON.

One console error appeared on every page: a React hydration-mismatch warning caused by a
`one-sec-browser-extension-id` attribute a Chrome extension injects before React hydrates. This
is an artifact of the testing browser, not an application bug — confirmed by reading the error's
own diff, which names the extension attribute as the sole mismatched attribute.

Screenshots from this session are committed at `docs/screenshots/*.png` and embedded in the
README's Demo section.

## Test coverage by phase

| Phase | Area | Tests | Status |
| --- | --- | --- | --- |
| 0 | Settings, cache, gateway | `test_settings`, `test_cache`, `test_gateway` | automated, pass |
| 1 | Registry, fetcher, coverage | `test_registry`, `test_fetcher_retry`, `test_fetch_all`, `test_inbox_names`, `test_scope` | automated, pass |
| 2 | Extraction, grounding, units | `test_extract_runner`, `test_grounding_numbers`, `test_units`, `test_chunk`, `test_answer_parse` | automated, pass |
| 3 | Clustering, graph load, queries | `test_cluster`, `test_graph_loader`, `test_graph_queries`, `test_gsql_schema`, `test_mentions`, `test_graph_names` | automated, pass; **live graph verified** (see below) |
| 4 | RAG, budgets, citations | `test_budget`, `test_citations`, `test_render`, `test_tracer_usage`, `test_vector_search` | automated, pass |
| 5 | Scorers, judge, stats, runner resume | `test_scorers`, `test_judge`, `test_stats`, `test_taxonomy`, `test_normalize_answers`, `test_persist`, `test_compare`, `test_runner_resume` | automated, pass |
| 6 | GraphRAG linking, expansion, ranking | `test_linking`, `test_relations`, `test_expand_caps`, `test_rank`, `test_serialize`, `test_linked_text`, `test_graphrag_fixture` | automated, pass on fixtures; **live run verified** (below), no test-split eval run yet |
| 7 | Guardrails, calculator, agent loop, verifier | `test_guardrails`, `test_calculator`, `test_agent_budget`, `test_agent_fuzz`, `test_agent_tools`, `test_verifier`, `test_agent_fixture`, `test_agent_injection` | automated, pass; **live graph tools verified** (below), no eval run yet (Groq daily rate limit) |
| 8 | API routes, demo mode, cache | `test_api_*`, `test_cached_answers_file`, `test_api_demo` | automated, pass |
| 8 | Dashboard | Vitest suite, Playwright smoke and graph tests | see the entry below |
| 9 | Pipeline contract on the smoke set | not written | **open** |
| 9 | Smoke-set regression fixture (Step 2) | not written | **open** |

## Security checklist (Phase 9 Step 7)

| Check | Result |
| --- | --- |
| No secrets in git history | `git log -p --all -S 'gsk_'` returns nothing. Re-run before tagging with a dedicated scanner (for example gitleaks) |
| `.env` not committed | `git ls-files .env` is empty; `.env` is listed in `.gitignore` |
| API bound to localhost in Compose | `127.0.0.1:` prefixes on the api and dashboard ports |
| Guardrail tests pass | yes (unit suite above) |
| Demo mode is the Compose default | yes (`DEMO_MODE` defaults to `true`) |
| Disclaimer visible | README section, and confirmed in the browser: the orange banner ("Research demo... Not investment advice.") appears at the top and bottom of every dashboard page |
| Only public data in samples | `data/samples/cached_answers.jsonl` holds answers built from the public filings; reviewed by reading, not by a scanner |

## Fresh-clone record (Phase 9 Step 11)

**Not done.** The plan calls for a clone on a second machine with only Git and Docker. That has
not happened. The closest check run here is in the section below.

## Clean-clone unit run

A clean clone of the branch was tested to catch dependence on uncommitted or ignored files. See
the entry below for the result.

## Known gaps before submission

1. Final test-split runs for GraphRAG and the agent against the now-working live graph
   (`docs/results.md`) — blocked today on the Groq daily rate limit (see above); one live
   question was verified end to end, but no eval-harness run has been stored.
2. No `auditor` records extracted for TATAMOTORS/TATASTEEL, so `AUDITED_BY` is empty for those
   companies — a data-coverage gap, not a code bug (see above).
3. Question set far below target size and missing three categories (`docs/evaluation.md`).
4. Smoke-set regression fixture and pipeline contract test.
5. Fresh-clone test on an actual second machine (the clean-clone backend check above is the
   closest substitute run from here).
6. Judge calibration (`server/eval/calibrate.py`) has never been run against a labelled sample.
7. API Docker image never finished building here: `uv sync` pulls full CUDA torch wheels
   (400MB+ for nvidia-cublas alone), and two attempts each ran 20-40+ minutes without finishing
   before being cut off for time. Fix: pin a CPU-only torch wheel, e.g. add an
   `[[tool.uv.index]]` for `https://download.pytorch.org/whl/cpu` scoped to `torch`, then
   `uv lock` and rebuild — should cut the image by gigabytes and the build by most of that time.
   The dashboard image builds and runs correctly (`docker build -t interlock-dashboard ./dashboard`
   then `docker run`, smoke-tested with a `200` response).

## Live TigerGraph verification (2026-10-07)

The workspace's existing global vertex/edge types collided with ours (an older `Interlock` graph,
plus an unrelated fraud-sample graph with its own `Account`/`Transfer_Transaction`/`Phone`
types), and all 8 GSQL query files had real bugs independent of that: V1/V2 syntax mismatches, a
reserved word (`target`), and `PRINT` inside `POST-ACCUM`. Both are fixed (`server/graph/names.py`
prefixes our types `IL_` on a new graph, `InterlockV2`, and maps names back to logical ones at the
Python boundary; the query files are rewritten for V2 syntax — see `server/graph/gsql/queries/`).

The TigerGraph Savanna workspace itself was also found paused ("Failed to start workspace: Auto
start is not enabled"). It was resumed through the TigerGraph Cloud console (an already
authenticated browser session; not a credential I was given or entered).

**Schema, queries and data loaded and verified against `InterlockV2`:**
- All 8 queries compile and install (`succeeded: 8, skipped: 0, failed: 0`).
- Data loaded from the existing run store: 5 Company, 27 Person, 4 AuditFirm, 26 Document, 18,994
  Chunk, 28 DIRECTOR_OF, 8 AUDITED_BY, 1 SUBSIDIARY_OF, 3,240 MENTIONS, 18,994 HAS_CHUNK.
- `expand_hop` and `shared_directors` return correct results against real data, confirmed by hand:
  `shared_directors(["C:TATAMOTORS", "C:TATASTEEL"])` correctly finds **N. Chandrasekaran** as the
  common director — Phase 3's exit criterion 7 ("interesting multi-hop links exist").
- **`uv run hl ask "Which director sits on the boards of both Tata Motors and Tata Steel?" --pipeline graphrag`**
  completed the full graph path end to end: `link_plan → link_entities → choose_relations →
  expand_hop(hop 1) → expand_hop(hop 2) → linked_text → final_answer`, answered correctly, and
  cited the graph triples themselves (e.g. `"Person: N. Chandrasekaran —[DIRECTOR_OF: ...]→
  Company: Tata Steel Limited"`), not a vector-search fallback.
- **`uv run hl ask "Who audited Tata Steel in FY2023-24?" --pipeline agent`** used the `neighbors`
  and `expand_hop` graph tools without error, found no `AUDITED_BY` edge for Tata Steel (a real
  data-coverage gap, see below), tried `search_text`, and correctly abstained (`not_found`)
  instead of hallucinating.

**Two real bugs found and fixed while verifying against live data (not design flaws in the
rename approach itself):**
1. `NamedConnection.map_forward` (the wrapper that prefixes type names before they reach
   TigerGraph) only recursed into `str` and `list`, not `dict`. `runInstalledQuery` is called with
   a params *dict* (`{"edge_types": ["DIRECTOR_OF", ...]}`), so the type names inside it were
   never actually prefixed, while the installed query's own text had the prefix baked in — every
   query silently returned zero rows, no error. Fixed; covered by `tests/unit/test_graph_names.py`.
2. `build_mentions` created a `context_company` mention for `directors`, `rpt` and `subsidiaries`
   records, but not for `auditor` records, so the loader could never resolve the reporting-company
   side of an `AUDITED_BY` edge — every extracted auditor fact was silently dropped (0 edges, no
   error). Fixed; covered by `tests/unit/test_mentions.py`.

**Known gap, not a bug:** no `auditor` records were ever extracted for TATAMOTORS or TATASTEEL
(only BAJFINANCE and BAJAJFINSV have them) — `SELECT ... FROM records WHERE record_type='auditor'
AND company_id IN ('TATAMOTORS','TATASTEEL')` returns zero rows of any status. RAG's correct "who
audited Tata Motors" answer comes from vector search over raw chunk text, bypassing the
structured-records pipeline entirely; the graph has nothing to cite for that specific question.
Fixing this needs re-running LLM extraction for the `auditor` task against those companies'
documents.

**Still open:** no GraphRAG or agent test-split eval run. This session's Groq key hit its daily
token rate limit (200k TPD) partway through live verification; further LLM-backed runs will fail
until the quota resets. `docs/results.md` is not updated with new eval numbers for this reason —
only the single verified live question above.
