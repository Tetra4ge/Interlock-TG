# Results

**Status: incomplete.** This file reports only what the stored runs show. The planned final
evaluation (all three pipelines on the test split, Phase 9 Step 8) has **not** been run, because
it needs a live TigerGraph graph with the `Interlock` schema and loaded data, which was not
reachable. Until it is, the headline comparison in the README is not supported.

## Question set

- `data/eval/questions_v1.jsonl`: **17 questions** (5 dev, 12 test). Categories present:
  `single_fact` (10), `unanswerable` (5), `numerical` (2). `multi_hop`, `temporal` and `global`
  have **no questions yet**.
- The target in `CLAUDE.md` is 150–300 questions across six categories. The set is far below
  that, so no per-category claim should be read as established.

## Runs on record

| run_id | pipeline | split | git commit | clean tree | n | accuracy (95% CI) | notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `rag-test-20261007T014855` | RAG | test | `17cfed3` | yes | 12 | 1.00 (1.00–1.00) | **latest clean test run** |
| `rag-test-v1` | RAG | test | `df6f158` | no | 8 | 0.875 (0.625–1.00) | earlier run |
| `phase5-test-v2`, `phase5-test-v3` | RAG | test | `9acc876` | no | 12 | 1.00 (1.00–1.00) | earlier runs, same commit |
| `phase7-rag-dev` | RAG | dev | `24d9391` | no | 5 | 0.60 (0.20–1.00) | |
| `phase7-agent-dev-nograph` | Agent | dev | `f26eae8` | no | 5 | 0.40 (0.00–0.80) | graph tools unavailable; 2 `bad_query` errors |

Reading the RAG test numbers: with 12 questions, a 1.00 accuracy has a degenerate interval
(1.00–1.00) and says little about the true rate. Citation accuracy is 0.33 in the latest run, so
citations are the weak point even where answers are correct. Evidence recall is 0.44.

## Costs and latency (latest clean run, `rag-test-20261007T014855`)

- Median latency 32.0 s, p90 35.7 s. Cost reported as $0.00 because the Groq free tier was used.
  Treat the cost figure as a placeholder, not a measurement.
- LLM calls per question: 1.0 on average.

## GraphRAG and Agentic GraphRAG

No test-split runs exist for either. The only agent run is a dev run with **no graph**, so it does
not measure the agent. The Phase 6 and Phase 7 exit criteria that depend on graph-enabled runs
remain open (see `docs/test-plan.md`).

## Failure labels

- `phase7-rag-dev`: `hallucination` 1, `wrong_abstention` 1.
- `phase7-agent-dev-nograph`: `bad_query` 2, `wrong_abstention` 1.

## Limitations

- 17 questions, of which 12 are test; no `multi_hop`, `temporal` or `global` coverage.
- Gold answers and verification status are documented in `docs/evaluation.md`, which does not
  exist yet. Do not cite accuracy numbers from this file as verified until it does.
- No graph-enabled run has been made, so the central claim (graph retrieval helps multi-hop
  questions) is untested.
- Costs are not measured on a paid tier.

## Reproducing

```bash
uv run hl eval --pipeline rag --split test --run-id rag-test-20261007T014855
```

The run store is `db/interlock.db`; the per-question records are in
`data/eval/runs/<run_id>/`.
