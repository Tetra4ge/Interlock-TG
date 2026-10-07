# Test plan and Phase 9 checklist

This records what is verified, by whom and how, and what is not. "Verified" means run in the
environment noted; nothing here is claimed beyond that.

## Automated checks

| Check | Command | Result (2026-10-07, macOS, Python 3.11) |
| --- | --- | --- |
| Unit tests | `uv run pytest -q` | 782 passed, 4 deselected (integration) |
| Lint (server, tests, spikes) | `uv run ruff check server tests spikes` | passed |
| Format | `uv run ruff format --check server tests spikes` | passed |
| Type check | `uv run mypy server` | passed (127 files) |
| Dashboard build | `npm run build` | passed |
| Dashboard typecheck | `npm run typecheck` | passed (run after `build`; Next generates route/layout types that typecheck needs — see CI step order) |
| Dashboard unit tests | `npm test` | 55 passed |
| Dashboard lint | `npm run lint` | passed |
| Compose file | `docker compose config -q` | passed |
| API image | `docker build --platform linux/amd64 -t interlock-api .` | failed on a transient network error downloading a CUDA package mid-build (not a code issue); not yet retried to completion |
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
| 3 | Clustering, graph load, queries | `test_cluster`, `test_graph_loader`, `test_graph_queries`, `test_gsql_schema` | automated, pass; live graph not verified |
| 4 | RAG, budgets, citations | `test_budget`, `test_citations`, `test_render`, `test_tracer_usage`, `test_vector_search` | automated, pass |
| 5 | Scorers, judge, stats, runner resume | `test_scorers`, `test_judge`, `test_stats`, `test_taxonomy`, `test_normalize_answers`, `test_persist`, `test_compare`, `test_runner_resume` | automated, pass |
| 6 | GraphRAG linking, expansion, ranking | `test_linking`, `test_relations`, `test_expand_caps`, `test_rank`, `test_serialize`, `test_linked_text`, `test_graphrag_fixture` | automated, pass; fixture graph only |
| 7 | Guardrails, calculator, agent loop, verifier | `test_guardrails`, `test_calculator`, `test_agent_budget`, `test_agent_fuzz`, `test_agent_tools`, `test_verifier`, `test_agent_fixture`, `test_agent_injection` | automated, pass; no live graph run |
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

1. Final test-split runs for GraphRAG and the agent, with a live graph (`docs/results.md`).
2. Question set far below target size and missing three categories (`docs/evaluation.md`).
3. Smoke-set regression fixture and pipeline contract test.
4. Fresh-clone test on an actual second machine (the clean-clone backend check above is the
   closest substitute run from here).
5. Judge calibration (`server/eval/calibrate.py`) has never been run against a labelled sample.
6. API Docker image: last build attempt failed on a transient network error, not retried to a
   clean finish yet.

## Live TigerGraph findings (checked 2026-10-07, read-only unless noted)

- Reachable: the Savanna workspace in `.env` answers `echo`.
- The `Interlock` graph holds data from an earlier load: 3 Company, 27 Person, 26 Document,
  18,994 Chunk, 28 DIRECTOR_OF. AuditFirm, RelatedPartyTxn and RegulatoryAction are empty.
- The workspace's vertex types include AML-style types (`Account`, `Transfer_Transaction`,
  `Phone`, ...) that are not in `server/graph/gsql/schema.gsql`, so the live graph's schema does
  not match the repo. Clearing it (`CLEAR GRAPH STORE -HARD`) would delete that data.
- No GSQL queries are installed. `install_queries` skipped the install because the lock file
  matched the query files, while the queries were absent on the cluster.
- Fixed: `install_queries` did not select the graph, so the install failed with "Currently not
  using any graphs". It now prefixes `USE GRAPH <name>`.
- Still failing: all eight queries fail the V2 syntax check. Each file declares `SYNTAX v2`, but
  the bodies use V1 constructs. `entity_neighbors` also references a `Transfer_Transaction`-style
  edge path that the repo schema does not define.

Consequence: GraphRAG and the graph-enabled agent cannot run against the cluster, so their
test-split runs (Phase 6, Phase 7) remain open.
