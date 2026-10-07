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
| Dashboard typecheck | `npm run typecheck` | see the entry below |
| Dashboard unit tests | `npm test` | see the entry below |
| Dashboard build | `npm run build` | see the entry below |
| Compose file | `docker compose config -q` | passed |
| API image | `docker build -t interlock-api .` | see the entry below |

Integration tests (`pytest -m integration`) are not run in CI. They need a live TigerGraph and a
real LLM, and the integration test drops and recreates a graph. Run them locally before tagging.

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
| Disclaimer visible | README section; dashboard sidebar to be confirmed in the browser |
| Only public data in samples | `data/samples/cached_answers.jsonl` holds answers built from the public filings; reviewed by reading, not by a scanner |

## Fresh-clone record (Phase 9 Step 11)

**Not done.** The plan calls for a clone on a second machine with only Git and Docker. That has
not happened. The closest check run here is in the section below.

## Clean-clone unit run

A clean clone of the branch was tested to catch dependence on uncommitted or ignored files. See
the entry below for the result.

## Known gaps before submission

1. Final test-split runs for GraphRAG and the agent, with a live graph (`docs/results.md`).
2. Question set far below target size and missing three categories.
3. Smoke-set regression fixture and pipeline contract test.
4. Fresh-clone test on a second machine.
5. `docs/evaluation.md` (question verification and judge calibration) is missing.
6. Architecture diagram is an SVG drawn from the code; no PNG export.
