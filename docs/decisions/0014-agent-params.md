# ADR-0014: Agent Parameters, Guardrails and Known Gaps

The phase plan names this record `0013-agent-params.md`; `0013` was already taken by the GraphRAG ADR, so this is `0014`.

## Status
Accepted for the implementation. **Not tuned and not evaluated against a working graph**: the parameters are the plan's start values, the tuning history below is a handful of real-run fixes rather than a dev-set sweep, and the only dev numbers are for a text-only agent (see "Results" and "Verification status").

## Context
The agent is the headline system: an LLM that picks tools in a loop while code decides what is allowed and when to stop. It must be compared like-for-like with RAG and GraphRAG, so its answer, citations, evidence budget and model are the shared ones; only retrieval differs.

## Parameters (`config/pipeline.yaml: agent`)

| Parameter | Value | Why |
| --- | --- | --- |
| `max_steps` | 8 | Plan start value. A step is one tool call (calls past the budget in a parallel turn are answered with an error, not run). |
| `max_tokens` | 40,000 | **Cumulative** prompt + completion tokens across turns, as in the plan. History is replayed every turn, so this binds well before 8 steps if tool output is large. |
| `timeout_seconds` | 120 | Wall clock for the loop (the final answer and verifier run after it). |
| `gsql_timeout_seconds` / `gsql_max_rows` | 10 / 200 | Per graph call; at most 200 rows read, 60 shown (`shown_rows`) with a "N more rows truncated" note. |
| `tool_output_tokens` | 1500 | Cap on any single tool result: output is replayed on every later turn, so uncapped results make cost grow quadratically. |
| `graph_query_max_failures` | 2 | After two `graph_query` failures (rejections count) the tool is removed from the request for the rest of the question. |
| `neighbors_default_limit` / `neighbors_max_limit` | 40 / 60 | Facts shown per `neighbors` call. |
| `search_max_k` | 8 | Chunks per `search_text`. |
| `verify_enabled` | true | The verifier costs one extra LLM call (two if it triggers a repair). |

Models: the agent, the shared final answer and the verifier all use the answerer model (`openai/gpt-oss-20b`); the faithfulness judge in eval stays on `openai/gpt-oss-120b`. The verifier deliberately shares the answerer's model so the three pipelines differ only in retrieval, at the cost of a model grading its own family's output; `VERIFIER_MODEL` is one constant to change.

## Decisions that differ from the plan
1. **Tool-aware LLM messages were missing.** The gateway could send tool definitions and parse tool calls, but `LLMMessage` was plain role/content, so a second turn could not replay the assistant's calls or tag results with `tool_call_id` (Groq rejects that). Messages now carry both; cache keys omit the new fields when unused, pinned by a test, so existing cached responses stay valid.
2. **The final-answer prompt gets the evidence log, not the agent's notes**, as the plan suggests. The agent's last message is only used to see which `[E#]` labels it relied on.
3. **Evidence prioritisation uses relevance, not just recency.** The plan orders cited -> last 3 steps -> rest. On a real run the agent flailed, its last steps were its worst, and recency pushed the genuinely relevant evidence out of the budget. When the log does not fit, items are ordered by embedding similarity to the question (cited first, small recency bonus); if scoring fails it falls back to recency. Nothing changes when everything fits.
4. **`get_evidence` accepts the `E#` labels** the model is shown, because it never sees `ref_id`s; search results are previews and this reads the full text.
5. **A provider-side "tool call validation failed" (HTTP 400) is a retry request, not a crash** (max 2 per question). Groq validates tool calls against the JSON Schema; the model passed `C:TATASTEEL` where `search_text` wanted `TATASTEEL`. The tool now accepts both.
6. **Guardrail hardening beyond the plan.** (a) The plan's `^...$` with `re.match` lets a trailing newline through (`"C:1\n"`); values use `fullmatch`. (b) Parameter models forbid unknown fields. (c) The calculator also bounds integer size, because the plan's per-level exponent cap still allows `((9**10)**10)**10...` to grow without limit. Seeded fuzz tests cover all three.
7. **The verifier also checks numbers in code**: a numeric answer must appear in the evidence (a `calculate` result or a fact, after unit formatting) within 1%, so a lenient verifier model cannot wave through an invented figure.
8. **Verifier calls count as LLM calls** in `usage.llm_calls` (the plan says they count toward cost); the local citation check, also `kind="verify"`, spends no tokens and is not counted.
9. **Failure taxonomy**: a wrong answer with `status=budget_exceeded` is labelled `budget_loop`. A budget-exceeded run that produced no answer is reported as `abstained` so it is not scored as a hallucination on unanswerable questions; the budget stop is in the trace. A loop that dies with no evidence at all is `error`, not an abstention.
10. **Read-only graph access is by allow-list only.** A separate read-only TigerGraph user/token is not configured (edition support unverified), so the only protection against writes is that the model never supplies query text and only four installed read-only queries are reachable. Review any new installed query for writes before adding it to `QUERY_REGISTRY`.

## Guardrails (defence in depth)
1. The prompt tells the model the rules (weakest layer). 2. `graph_query` accepts only names in `QUERY_REGISTRY`; parameters are typed Pydantic models, unknown fields are rejected, every string must `fullmatch` `[A-Za-z0-9_:\-|]{1,64}`. 3. Parameters go to pre-installed queries as typed values and are never concatenated into query text, so there is nothing to inject into. 4. Timeouts, a 200-row cap and a 1,500-token cap on output. 5. `calculate` evaluates a whitelist AST: numbers, `+ - * / % **`, lists and `sum/min/max/round/abs` only.

## Verification status (read this before trusting any number)
- **Tests**: 600+ unit and fixture tests pass, including the plan's block/allow lists, seeded fuzzing of the guardrails and calculator, loop and budget behaviour, and integration runs through the real loop, tools, evidence log, shared final answer and verifier for the temporal, numeric, repair, budget, outage and prompt-injection scenarios. The LLM and the graph/vector seams are scripted in those.
- **A real agent run against Groq works end to end** (tool calls, rejected-call recovery, budgets, final answer, verifier path), and found the bugs in decisions 3-5.
- **No graph tool has run against a live TigerGraph.** The cluster authenticates but the graph named in `.env` (`TG_GRAPH`, resolves to `SpikeGraph`) does not exist on it, so `expand_hop` (404) and the four allow-listed queries are untested live, as is `get_evidence` for edges. `hl build-graph --from schema` against a cluster with the `Interlock` graph is the first thing to run. Until then the agent is effectively text-only.
- **Not done:** graph-enabled dev runs, parameter tuning (plan Step 11), the single test-split run (plan Step 12: deliberately not spent on a degraded system), a paired comparison with meaningful CIs (5 dev questions), review of 10-20 failures and the demo success/failure picks.
- **Exit criteria:** 1 (guardrail and calculator tests) and 5 (this ADR) are met. 2 is half met (a dev run is stored with failure labels; the test run is not). 4 is reported for a text-only dev run only. 3 and 6 are open.

## Results (dev split, text-only agent, TigerGraph graph unavailable)
Runs: `phase7-rag-dev` and `phase7-agent-dev-nograph` (5 dev questions: 3 single_fact, 2 unanswerable), both with the faithfulness judge.

| | RAG | Agent (text-only) |
| --- | --- | --- |
| correct (single_fact, n=3) | 0.33 | 0.33 |
| correct (unanswerable, n=2) | 1.00 | 0.50 |
| faithfulness | 1.00 | 1.00 |
| citation accuracy | 0.25 | 1.00 |
| evidence recall | 0.33 | 0.33 |
| LLM calls / question | 1.0 | 5.4 |
| tool calls / question | 0 | 3.4 |
| median latency | 9 s | 57 s |
| budget-exceeded rate | 0 | 0 |
| cost / question | $0 (free tier) | $0 (free tier) |

**Two of the five agent answers are invalid.** `Q-SF-0008` and `Q-UNA-0004` ended as `error` (labelled `bad_query`) because Groq's free-tier **daily token limit (200,000) for `gpt-oss-20b` was exhausted** by real-run testing earlier the same day; this is infrastructure, not the agent. They remain in the stored run (the runner treats stored results as done) and are counted as wrong in the table above, so the agent's 0.50 on unanswerable and the `bad_query` count understate it. Re-run them once the quota resets (delete those two lines from `results.jsonl`, then `hl eval ... --run-id phase7-agent-dev-nograph`).

What the three valid agent answers show: no accuracy difference from RAG on single-fact (both get one right; the agent's one answer was `M/s B S R & Co. LLP`, which the scorer originally marked wrong until the `M/s` prefix was normalised), much better citation accuracy, and about 5x the LLM calls and 6x the latency. With n=3 and n=2 none of this is statistically meaningful (`hl compare` reports "too few pairs"); it demonstrates that the harness, scoring and reporting work, not that the agent is better or worse.

## Observed failure modes
- **Guessing names.** The 20B model searched for "KPMG" after a search for "statutory auditor" returned the auditor's report but not the firm's name; it never read the rest of the chunk. Mitigated (not solved) by the prompt rule and `get_evidence(E#)`.
- **Slow turns.** Individual turns took 10-30 s under Groq rate limiting, and the reranker adds ~3 s per search after a ~20 s first load, so a question can take minutes.
- **Plateau on repeated searches.** Without the graph, `search_text` variations are the only move; identical calls are refused but near-identical ones are not.

## Tuning history
No dev-set sweep (the graph was unavailable). Changes made from real-run evidence, one at a time: schema tolerance for `company_id`; recoverable tool-call rejections; relevance-ordered evidence; `get_evidence` by label; the "search for concepts, not names" rule. Tuning order for when a graph is available is the plan's: tool descriptions, then the `graph_query` catalogue, then `neighbors` limits, then budgets, then verifier strictness, watching accuracy by category, mean cost, mean steps and budget-exceeded rate.

## Consequences
- Phase 8's `/compare` can run `rag`, `graphrag` and `agent` through the shared `Pipeline` protocol; per-pipeline errors surface as `status=error`.
- To add a graph query to the agent: write the installed GSQL (read-only, bounded output), add an args model and a `to_gsql_params` mapping, add it to `QUERY_REGISTRY` and the catalogue text, and extend the guardrail tests.

## Update (2026-10-07)

"No graph tool has run against a live TigerGraph" above is now out of date. The graph is live
(`InterlockV2`, see `docs/test-plan.md`), and `uv run hl ask "Who audited Tata Steel in
FY2023-24?" --pipeline agent` exercised `neighbors` and `expand_hop` without error. It found no
`AUDITED_BY` edge for Tata Steel — a real data-coverage gap (no `auditor` records were ever
extracted for that company), not a tool failure — and correctly abstained rather than
hallucinate. A second run against a question the data does cover was cut off by Groq's daily
token rate limit before finishing. Still open: a dev/test eval run against the live graph, and
the resulting tuning pass; exit criteria 2, 3, 4 and 6 remain as stated above.
