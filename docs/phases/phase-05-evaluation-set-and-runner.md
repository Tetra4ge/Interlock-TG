# Phase 5 — Evaluation Set, Scorers, Judge and Runner

> **Accuracy note.** Cypher and code are sketches; verify against your schema and library docs. Category shares and thresholds are starting points, not facts.

---

## 5.1 Overview

| Item | Detail |
| --- | --- |
| Goal | A frozen, verified question set (dev + test), type-specific scorers, a calibrated LLM judge, a failure labeler, and one command that runs any pipeline over any split and stores scored, reproducible results |
| Why | This is how you prove anything. Built before GraphRAG and the agent, it measures them honestly instead of being shaped around them |
| Prerequisites | Phase 4 complete |
| Produces | `eval/` package, `eval/templates/*.yaml`, `data/eval/questions_v1.jsonl`, `questions`/`runs`/`results`/`scores` rows, `docs/evaluation.md`, first RAG test results |
| PRD links | FR-29 to FR-34, NFR-02, NFR-04 |
| TRD links | §5 (`questions`, `runs`, `results`, `scores`), §3.3 `eval` |

---

## 5.2 Concepts you will learn

### Dev/test discipline
- **Dev set:** you look at it, debug on it, tune prompts and parameters on it.
- **Test set:** you run it only to report numbers. If you tune on it, your numbers are optimistic and meaningless.
If you change the test set after seeing results, create a new version and rerun everything.

### Gold answers from the graph (and their bias)
Generating gold answers with Cypher is fast and consistent, but if the graph has an error, the gold answer inherits it — and GraphRAG, which reads the same graph, looks "right" when it is wrong. Checking gold answers against the original PDFs breaks this circularity.

### Matching metric to answer type
- Single entity → exact match after normalization.
- List → set precision/recall/F1 (partial credit for partial lists).
- Number → correct within a relative tolerance and in the right unit.
- Free text → LLM judge with a rubric.
Using an LLM judge for everything adds noise and cost; use code whenever the answer has structure.

### LLM-as-judge
A model grades answers. Known problems: inconsistency, favoring longer answers, favoring its own model family. Mitigations: give it the gold answer and a strict rubric, use a different model family from the answerer, and **measure** its agreement with your own labels before trusting it.

### Confidence intervals by bootstrap
With 30 questions in a category, 70% vs 77% might be noise. Bootstrap: resample the per-question scores with replacement many times, compute the mean each time, and take the 2.5th and 97.5th percentiles as a 95% interval. Overlapping intervals → don't claim a clear winner. For comparing two pipelines on the same questions, bootstrap the **paired difference** (resample question IDs, compute the difference of means) — this is more sensitive than comparing separate intervals.

---

## 5.3 Files created

```
src/hidden_links/eval/
├── __init__.py
├── models.py            # Question, Template, RunConfig, ScoreRow
├── templates/
│   ├── single_fact.yaml
│   ├── multi_hop.yaml
│   ├── temporal.yaml
│   ├── numerical.yaml
│   ├── global.yaml
│   └── unanswerable.yaml
├── generate.py          # templates + Cypher → candidate questions
├── paraphrase.py        # natural wording via helper LLM
├── verify_ui.py         # Streamlit page for PDF verification
├── split.py             # stratified dev/test split + freeze
├── normalize.py         # answer normalizers
├── scorers.py           # exact, set F1, numeric, abstention, citation, evidence recall
├── judge.py             # LLM judge + prompts
├── calibrate.py         # judge agreement with human labels
├── taxonomy.py          # failure labeler
├── stats.py             # bootstrap CIs, paired differences
└── runner.py            # hl eval
src/hidden_links/eval/prompts/
├── paraphrase_v1.md
├── judge_correctness_v1.md
├── judge_faithfulness_v1.md
└── failure_label_v1.md
data/eval/questions_v1.jsonl
data/eval/judge_calibration_v1.jsonl
docs/evaluation.md
tests/unit/test_normalize_answers.py, test_scorers.py, test_stats.py
tests/integration/test_runner_resume.py
```

---

## 5.4 Step-by-step implementation

### Step 1 — Question model (`eval/models.py`)

```python
class GoldEvidence(BaseModel):
    doc_id: str
    page: int
    edge_id: str | None = None
    chunk_id: str | None = None

class Question(BaseModel):
    qid: str                      # "Q-MH-0042"
    version: str                  # "v1"
    question: str                 # final natural wording
    question_raw: str             # template-filled wording (kept for audit)
    category: str                 # single_fact|multi_hop|temporal|numerical|global|unanswerable
    answer_type: AnswerType
    gold_answer: list[str] | str | float | None   # list for LIST, float for NUMBER, None for unanswerable
    gold_unit: str | None = None  # e.g. "crore"
    gold_evidence: list[GoldEvidence]
    template_id: str | None
    split: str | None = None      # dev|test after freezing
    difficulty: str | None = None # easy|medium|hard (hops, filters)
    verified: bool = False
    verification_note: str | None = None
```

### Step 2 — Templates

Each template is YAML with the question pattern, the parameter query (which entities to fill in), and the gold query.

**Example: multi-hop (`templates/multi_hop.yaml`)**

```yaml
- template_id: MH-01
  category: multi_hop
  answer_type: list
  difficulty: medium
  question: "Which companies in the dataset share at least one director with {company}?"
  params_cypher: |
    MATCH (c:Company {in_dataset:true})<-[:DIRECTOR_OF]-(:Person)-[:DIRECTOR_OF]->(o:Company {in_dataset:true})
    WHERE c <> o
    RETURN DISTINCT c.entity_id AS company_id, c.name AS company
    LIMIT 40
  gold_cypher: |
    MATCH (c:Company {entity_id:$company_id})<-[r1:DIRECTOR_OF]-(p:Person)-[r2:DIRECTOR_OF]->(o:Company {in_dataset:true})
    WHERE o <> c
    RETURN collect(DISTINCT o.name) AS answer,
           collect(DISTINCT {doc_id:r1.doc_id, page:r1.page, edge_id:r1.edge_id}) +
           collect(DISTINCT {doc_id:r2.doc_id, page:r2.page, edge_id:r2.edge_id}) AS evidence

- template_id: MH-02
  category: multi_hop
  answer_type: list
  difficulty: hard
  question: "Which directors of {company} also sit on the board of a company named in a regulatory order?"
  params_cypher: |
    MATCH (c:Company {in_dataset:true})<-[:DIRECTOR_OF]-(p:Person)-[:DIRECTOR_OF]->(o:Company)-[:NAMED_IN]->(:RegulatoryAction)
    WHERE c <> o
    RETURN DISTINCT c.entity_id AS company_id, c.name AS company LIMIT 40
  gold_cypher: |
    MATCH (c:Company {entity_id:$company_id})<-[r1:DIRECTOR_OF]-(p:Person)-[r2:DIRECTOR_OF]->(o:Company)-[r3:NAMED_IN]->(a:RegulatoryAction)
    WHERE o <> c
    RETURN collect(DISTINCT p.name) AS answer,
           collect(DISTINCT {doc_id:r1.doc_id,page:r1.page,edge_id:r1.edge_id}) +
           collect(DISTINCT {doc_id:r3.doc_id,page:r3.page,edge_id:r3.edge_id}) AS evidence
```

**Template ideas per category** (write 3–6 per category):

| Category | Template ideas |
| --- | --- |
| Single-fact | Auditor of X in FY; is director D independent at X in FY; subsidiaries of X (short list); promoter holding % of X at date |
| Multi-hop | Companies sharing a director with X; directors of X on boards of companies named in orders; counterparties of X's RPTs whose directors overlap with X's board; companies sharing an auditor with X that also share a director |
| Temporal | Directors who joined X after X was named in an order; did X change auditor in the year after an order; directors present in FY1 but not FY3 |
| Numerical | Total RPT amount of X in FY (₹ crore); largest RPT counterparty of X by amount; change in promoter pledge % between two dates; number of independent directors of X in FY |
| Global | Sector with most auditor changes; person with the most board seats in the dataset; company with the highest total RPT/any normalization you can compute honestly |
| Unanswerable | Facts outside the years; metrics not collected (salaries, prices); false premise ("Why was X's auditor debarred in FY2022-23?" when it wasn't) |

Rules for templates:
- Gold must be **computable** by Cypher and **checkable** in PDFs.
- Avoid schema words in questions ("DIRECTOR_OF", "HOLDS_STAKE").
- For numerical templates, state the unit in the question and compute gold in that unit.
- Global questions must be well-defined ("across the three fiscal years in the dataset").

### Step 3 — Generate candidates (`eval/generate.py`)

For each template:
1. Run `params_cypher` → parameter rows.
2. Sample up to N rows (spread across companies; don't let one company dominate).
3. For each, run `gold_cypher` with parameters → answer + evidence.
4. Skip empty answers (except for templates intended to test "none" answers — keep a few of those deliberately, labeled).
5. Fill the question text; create `Question(question_raw=..., question=...)` with `verified=False`.

Target counts: 150–300 total, roughly matching category shares in `PRD`/`08` (single-fact ~15%, multi-hop ~25%, temporal ~15%, numerical ~15%, global ~15%, unanswerable ~15%). Aim for **at least ~20 test questions per category**, otherwise per-category results are too noisy to interpret.

### Step 4 — Paraphrase (`eval/paraphrase.py`)

`paraphrase_v1.md`:

```
Rewrite the question in natural English as an analyst would ask it.
Keep every entity name, year, unit and constraint exactly.
Do not add or remove conditions. Do not answer it.
Return only the rewritten question.

Question: {question_raw}
```

Then check automatically: every entity name and year string in `question_raw` still appears in the paraphrase (case-insensitive). If not, keep `question_raw`. Review a sample by eye.

### Step 5 — Hand-written questions

Add by hand:
- Unanswerable (~15%): outside scope, not collected, false premise.
- A few "tricky" answerable ones: two companies with similar names; a director with a common surname; a question needing the consolidated vs standalone distinction (only if your data supports it).

### Step 6 — Verification against PDFs (`eval/verify_ui.py`)

Streamlit page:
1. Shows the question, gold answer, and for each gold evidence item: the PDF page text (from parsed JSON) with the quote highlighted, plus a link/path to open the PDF at that page.
2. Buttons: **Correct**, **Fix answer** (edit gold), **Drop** (with reason).
3. Records `verified=True` and `verification_note`.

Policy:
- Verify **all** test questions if time allows; minimum a random 30%, reported.
- Every "Fix" or "Drop" caused by a graph error → also fix the data (review queue / resolution), and count it in `docs/evaluation.md`.

### Step 7 — Split and freeze (`eval/split.py`)

1. Stratify by category (and by template, so the same template's instances land in both splits proportionally).
2. ~30% dev, ~70% test. Use a fixed random seed.
3. Write `data/eval/questions_v1.jsonl` and insert into `questions` with `version='v1'`.
4. Record a checksum of the file in `docs/evaluation.md`. Any change → `v2`.

Template leakage note: dev and test share templates, so tuning on dev can overfit to template wording. Mitigation: paraphrasing (Step 4) and hand-written questions; optionally hold out 1–2 templates per category entirely for test.

### Step 8 — Answer normalization (`eval/normalize.py`)

```python
def norm_entity(s: str) -> str:
    return norm_company(s) or norm_person(s)          # reuse Phase 3 normalizers

def norm_list(s: str | list[str]) -> set[str]:
    items = s if isinstance(s, list) else re.split(r";|\n|,(?![^()]*\))", s)
    return {norm_entity(x) for x in items if x.strip()}

NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")

def parse_number(s: str, expected_unit: str | None) -> float | None:
    m = NUM_RE.search(s.replace("₹", ""))
    if not m:
        return None
    v = float(m.group().replace(",", ""))
    unit = detect_unit(s)                  # from Phase 2 units.py
    if unit and expected_unit and unit != expected_unit:
        v = to_rupees(v, unit) / MULTIPLIERS[expected_unit]
    return v
```

Entity matching tolerance: after normalization, also accept `fuzz.token_sort_ratio ≥ 92` for entity names (e.g. "Deloitte Haskins and Sells LLP" vs "Deloitte Haskins & Sells"). Record the tolerance in `docs/evaluation.md`.

### Step 9 — Scorers (`eval/scorers.py`)

| Scorer | Applies to | Output |
| --- | --- | --- |
| `score_entity` | ENTITY | 1.0 / 0.0 |
| `score_list` | LIST | F1 over normalized sets (with fuzzy item matching) |
| `score_number` | NUMBER | 1.0 if `abs(pred - gold) <= rel_tol * abs(gold)` else 0.0 |
| `score_date` | DATE | exact date match after parsing |
| `score_yes_no` | YES_NO | exact |
| `score_text` | TEXT | LLM judge (Step 10) |
| `score_abstention` | all | For unanswerable: 1 if pipeline returned not_found. For answerable: 1 if it did **not** |
| `citation_accuracy` | all with citations | share of citations whose (doc_id, page) contains the gold fact (page in gold evidence pages, or quote contains the gold value) |
| `evidence_recall` | all | share of gold evidence items (by edge_id, chunk_id or doc+page) present in the pipeline's evidence/trace |

Final `correct` for a question:
- Unanswerable: `score_abstention`.
- Answerable: type scorer, but **0 if the pipeline abstained**.

For set F1:

```python
def set_f1(pred: set[str], gold: set[str], match) -> float:
    if not pred and not gold: return 1.0
    if not pred or not gold: return 0.0
    tp = sum(1 for p in pred if any(match(p, g) for g in gold))
    precision = tp / len(pred)
    recall = sum(1 for g in gold if any(match(p, g) for p in pred)) / len(gold)
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
```

### Step 10 — LLM judge (`eval/judge.py`)

Two judge uses:
1. **Correctness** for TEXT answers.
2. **Faithfulness** for all answers: are the claims in `answer_long` supported by the evidence the pipeline actually had?

`judge_faithfulness_v1.md`:

```
You check whether an answer is supported by the evidence it was given.

Evidence:
{evidence_blocks}

Answer:
{answer_long}

Steps:
1. Split the answer into atomic factual claims.
2. For each claim, decide SUPPORTED (stated in the evidence) or UNSUPPORTED.
3. Ignore style; judge only factual support.

Return JSON: {"claims": [{"claim": "...", "verdict": "SUPPORTED|UNSUPPORTED", "evidence_label": "E2|null"}]}
```

Faithfulness score = supported claims ÷ all claims (1.0 if no factual claims, e.g. a clean abstention).

`judge_correctness_v1.md` gives the question, gold answer, predicted answer and a rubric: CORRECT (same meaning), PARTIAL (some required facts missing), INCORRECT; return verdict + one-line reason. Map to 1 / 0.5 / 0.

Use `role="judge"` in the gateway (different model family if available). Temperature 0.

### Step 11 — Judge calibration (`eval/calibrate.py`)

1. Take ~50 (question, answer, evidence) items from dev runs, mixed across pipelines and outcomes.
2. Label them yourself: faithfulness verdict per claim (or overall supported/unsupported) and correctness for text answers. Save to `data/eval/judge_calibration_v1.jsonl`.
3. Run the judge; compute agreement (% same verdict) and, optionally, Cohen's kappa (agreement corrected for chance).
4. If agreement is low, look at disagreements, adjust the prompt (new version), repeat.
5. Report the final agreement in `docs/evaluation.md`. Don't claim judge-based numbers are exact.

### Step 12 — Failure labeler (`eval/taxonomy.py`)

For each question with `correct < 1`:
1. **Rule-based first** (cheap, deterministic):
    - `status=budget_exceeded` → `budget_loop`
    - `status=error` and trace has Cypher error → `bad_cypher`
    - evidence_recall == 0 → `retrieval_miss`
    - answered not_found on answerable → `wrong_abstention`
    - NUMBER with right evidence retrieved but wrong value → `arithmetic_error`
    - faithfulness < 1 → candidate `hallucination`
2. **LLM suggestion** for the rest (`failure_label_v1.md`): give question, gold, answer, evidence IDs vs gold evidence IDs, and the taxonomy definitions; ask for one label + reason.
3. Hand-check a sample (e.g. 30) and report agreement.
4. `data_error` is only assigned by you during review; such questions are fixed in v2 or excluded, and counted.

Taxonomy (one primary label): `retrieval_miss`, `entity_link_error`, `missed_hop`, `temporal_error`, `arithmetic_error`, `hallucination`, `wrong_abstention`, `bad_cypher`, `budget_loop`, `data_error`.

### Step 13 — Runner (`eval/runner.py`)

```
hl eval --pipeline rag --split test [--version v1] [--limit N] [--concurrency 4] [--offline]
```

Algorithm:
1. Create `runs` row: `run_id`, pipeline, split, question version, full config JSON (models, prompts versions, retrieval params), git commit (`git rev-parse HEAD`; refuse to run on a dirty tree unless `--allow-dirty`), start time.
2. Load questions for the split.
3. For each question not yet in `results` for this run (resume support): call `pipeline.answer(q, request_id=f"{run_id}:{qid}")`; store `AnswerResult` JSON immediately.
4. Concurrency: a small thread pool (e.g. 4). Respect provider rate limits (the gateway retries).
5. After answering: score every question → `scores`.
6. Label failures.
7. Compute aggregates + bootstrap CIs; write `runs.finished_at`.
8. Print a summary table.

Resuming: `hl eval --resume <run_id>` continues an interrupted run with the same config.

### Step 14 — Statistics (`eval/stats.py`)

```python
import numpy as np

def bootstrap_ci(values: list[float], n: int = 2000, seed: int = 0, alpha=0.05):
    rng = np.random.default_rng(seed)
    arr = np.asarray(values, dtype=float)
    means = [rng.choice(arr, size=len(arr), replace=True).mean() for _ in range(n)]
    return float(arr.mean()), float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))

def paired_diff_ci(a: dict[str, float], b: dict[str, float], n=2000, seed=0, alpha=0.05):
    qids = sorted(set(a) & set(b))
    diffs = np.array([a[q] - b[q] for q in qids])
    rng = np.random.default_rng(seed)
    boots = [rng.choice(diffs, size=len(diffs), replace=True).mean() for _ in range(n)]
    return float(diffs.mean()), float(np.quantile(boots, alpha / 2)), float(np.quantile(boots, 1 - alpha / 2))
```

Aggregates per (run, category): mean correct + CI, mean faithfulness, citation accuracy, evidence recall, abstention rates, median and p90 latency, mean cost, mean LLM/tool calls.

### Step 15 — First RAG results

1. `hl eval --pipeline rag --split dev` — look at failures, fix bugs in scorers (not in RAG to game it).
2. `hl eval --pipeline rag --split test` — first reported baseline.
3. Save the summary in `docs/evaluation.md` under "Baseline".

### Step 16 — `docs/evaluation.md`

Contents:
- Purpose and categories with definitions and examples.
- How templates and gold queries work.
- Verification policy and results (verified count, fixes, drops, data errors found).
- Split method, seed, file checksum.
- Scorers and tolerances.
- Judge model family, prompt versions, calibration agreement.
- Failure taxonomy definitions and labeler agreement.
- Known biases and limitations (graph-derived gold; template leakage; small per-category samples).

---

## 5.5 Tests

| Test | Expectation |
| --- | --- |
| Normalizers | "₹ 12.5 crore" parses to 12.5 in crore; "1,25,00,000" in rupees → 1.25 crore |
| `set_f1` | Perfect, partial, empty-both, empty-pred cases |
| Numeric tolerance | Within 1% passes; unit mismatch converted |
| Abstention scoring | Unanswerable + not_found = 1; answerable + not_found = 0 |
| Bootstrap | Deterministic with seed; CI contains mean; narrow for constant data |
| Paired diff | Identical pipelines → diff 0 |
| Runner resume (integration) | Kill after 3 questions; resume completes without duplicates |
| Runner offline | With `--offline` and a full cache, no network calls |
| Gold queries | Every template's gold_cypher runs on the fixture graph without error |

---

## 5.6 Exit criteria

| # | Criterion | How to check |
| --- | --- | --- |
| 1 | Question set v1 frozen with checksum; ≥ ~20 test questions per category | `docs/evaluation.md` |
| 2 | Verification completed and reported (target 100% of test) | Verified counts |
| 3 | Judge agreement measured and reported | Calibration section |
| 4 | RAG dev and test runs stored with scores, CIs, failure labels | `runs`, `scores` |
| 5 | One command reproduces the RAG test run from cache with identical metrics | Rerun with `--offline` |

---

## 5.7 Pitfalls

| Symptom | Cause | Fix |
| --- | --- | --- |
| Every GraphRAG answer "correct", RAG always wrong | Questions mirror graph structure too literally | Paraphrase; add text-only facts; hand-written questions |
| Numeric scores near zero for all | Unit mismatch between gold and answer | State unit in question; normalize units in scorer |
| Judge says everything is faithful | Prompt too lenient | Claim-level verdicts; calibrate |
| Results change between reruns | Uncached calls or dirty git tree | Offline mode; refuse dirty runs |
| Too few questions in a category | Data lacks those links | Add templates or companies; or merge categories and say so |

---

## 5.8 Hand-off to Phase 6

Phase 6 builds GraphRAG and evaluates it with the same runner: `hl eval --pipeline graphrag --split dev|test`.
