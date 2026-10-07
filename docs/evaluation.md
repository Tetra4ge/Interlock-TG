# Evaluation

Methodology and current state of the evaluation harness. See `docs/results.md` for the numbers
produced by it, and `docs/test-plan.md` for what has and hasn't been verified.

## Question set

`data/eval/questions_v1.jsonl` — **17 questions**, frozen under this filename (no checksum file
yet; see Gaps).

| Category | Count | Target (CLAUDE.md) |
| --- | --- | --- |
| `single_fact` | 10 | ~20+ |
| `numerical` | 2 | ~20+ |
| `unanswerable` | 5 | ~20+ |
| `multi_hop` | 0 | ~20+ |
| `temporal` | 0 | ~20+ |
| `global` | 0 | ~20+ |

Split: 5 `dev`, 12 `test`. The project target is 150–300 questions across all six categories;
this set is well short of that, and three categories have no coverage at all. `multi_hop` and
`temporal` questions need the live graph to construct and verify gold answers against, which is
why they are missing (see `docs/decisions/0014-agent-params.md` and `docs/test-plan.md` for the
graph's current state).

## Gold answers and verification

Gold answers for `single_fact` and `numerical` questions were taken from the extracted records
and checked against the cited PDF page by hand during question authoring. **No separate,
recorded verification pass has been run** — there is no `docs/verification.md`-style log of
"N of M questions independently checked against the source PDF." Treat the gold answers as
author-reviewed, not independently audited.

`unanswerable` questions are deliberately out-of-corpus asks (for example, a CEO's favourite
food) that should produce an abstention; they don't need a gold fact, only a correct refusal.

## Scorers

`server/eval/scorers.py`:

- `score_entity` — exact/normalized match for single-entity answers.
- `score_list` / `set_f1` — set overlap for list answers (e.g. "list the independent directors").
- `score_number` — relative-tolerance match (`eval.numeric_rel_tolerance`, default 1%).
- `score_yes_no` — boolean match.
- `score_abstention` — correct refusal on `unanswerable` questions.
- `evidence_recall` — fraction of the gold evidence set the answer's citations actually cover.
- `citation_accuracy` — fraction of citations that point at a page where the quoted text is
  actually found (see the Inspector page's citation drawer for a worked example of a citation
  that fails this check while the answer itself is still scored correct).

## LLM judge

`server/eval/judge.py: judge_faithfulness` scores whether an answer's claims are supported by its
own cited evidence, using a separate model family from the answerer (judge prompt in
`_build_prompt`). **No calibration run has been made** — there is no agreement study against
human labels, so judge scores should be read as a secondary signal, not a validated metric.
`server/eval/calibrate.py` exists for this but has not been run against a labelled sample.

## Failure taxonomy

`server/eval/taxonomy.py` labels each wrong or errored answer with one cause: `retrieval_miss`,
`entity_link_error`, `missed_hop`, `temporal_error`, `arithmetic_error`, `hallucination`,
`wrong_abstention`, `bad_query`, `budget_loop`, `data_error`. The Failures dashboard page groups
by this label per pipeline (see `docs/screenshots/failures.png`).

## Runner and reproducibility

`uv run hl eval --pipeline <rag|graphrag|agent> --split <dev|test> [--run-id ID] [--judge]`
scores a pipeline against a split and writes to the run store (`runs`, `results`, `scores`
tables). `--run-id` resumes an existing run id rather than starting a new one, which is how the
offline cache keeps a rerun's numbers identical. `hl compare --a <run> --b <run>` computes a
paired per-category difference with a bootstrap 95% CI.

## Known biases and limitations

- The question set skews toward single-fact lookups answerable from one or two chunks, which
  favours RAG. No multi-hop or temporal question exists yet to test what graph retrieval is
  supposed to be good at.
- All test-split results on record are for RAG only; GraphRAG and the agent have no test-split
  runs (blocked on the live graph; see `docs/test-plan.md`).
- With only 5–12 questions per split, confidence intervals are wide and several reported
  accuracies are degenerate (0% or 100%). Treat every number here as indicative, not conclusive,
  per the warning banner on every dashboard page.
- The judge model and the answerer share an LLM provider (Groq), though not the same model
  family per call; this hasn't been independently verified as bias-free.

## Gaps before this can be called "done"

1. Expand the question set toward the 150–300 target, with real `multi_hop`, `temporal` and
   `global` questions once the graph is queryable.
2. Freeze the set with a recorded checksum (`CLAUDE.md`'s "frozen dev/test split").
3. Run and record an actual verification pass (N of M questions checked against source PDFs).
4. Run `calibrate.py` against a small labelled sample and report judge agreement.
