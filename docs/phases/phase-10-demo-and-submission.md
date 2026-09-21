# Phase 10 — Demo Video and Submission

---

## 10.1 Overview

| Item | Detail |
| --- | --- |
| Goal | A clear, honest demo video and a complete, checked submission of all four deliverables |
| Why | Judges often see the video before the code. It must show the comparison, the evidence and at least one failure — in a few minutes |
| Prerequisites | Phase 9 complete (final runs frozen, repo starts on a clean machine) |
| Produces | Demo script, recorded video, submission checklist completed, final tagged release |
| PRD links | G-6, US-01 to US-04, §7.2 |

---

## 10.2 Concepts you will learn

### Story over features
A demo is an argument: "Here is a real problem → here is how three approaches handle it → here is the evidence → here is what it costs → here is where it still fails." Every scene supports that argument; nothing else goes in.

### Show, don't claim
Every claim in the video should be visible on screen: the answer, the citation, the page, the metric with its confidence interval.

### Honesty as a strength
Showing a failure (with its label and trace) makes the successes believable, and the brief explicitly asks where each approach fails.

---

## 10.3 Step-by-step

### Step 1 — Read the submission rules again

Record in `docs/submission.md`:
- Video length limit and format.
- Where to upload (YouTube unlisted, Drive, platform upload).
- Required repo visibility and license.
- Required diagram format.
- Deadline with time zone.
- Anything about using pre-existing code or data (confirm your project complies).
- TigerGraph requirements: which products/features must be used (GSQL, `pyTigerGraph`, Savanna, TigerGraph's GraphRAG project, vector search), any required tags or write-up sections about the TigerGraph usage, and whether the judges expect a TigerGraph-hosted demo. Q-09 in the PRD tracks this.

### Step 2 — Choose the hero questions (from the test set)

Selection criteria for each:
- The difference between pipelines is visible in one screen.
- The answer is easy to understand without domain knowledge.
- The citation page looks clean when opened.
- It uses a real stored result (from the final runs) — no staged answers.

| Slot | What it shows | How to find it |
| --- | --- | --- |
| H1 | All three succeed (simple fact) | Filter single-fact questions where all three are correct; pick the cleanest |
| H2 | RAG fails, GraphRAG succeeds (multi-hop) | Failures page: pipeline=RAG failed, GraphRAG correct, category multi-hop; label `missed_hop` or `retrieval_miss` for RAG |
| H3 | Only the agent succeeds (temporal or numeric) | Agent correct, others wrong; agent trace shows `calculate` or year-aware steps |
| H4 | Agent fails honestly | Agent wrong with a clear label (`bad_query`, `budget_loop`, `entity_link_error`); trace shows why |
| Backup | One extra for each slot | In case something renders badly |

Add all hero questions to `data/samples/cached_answers.jsonl` so they work in demo mode.

### Step 3 — Script (target ~3–4 minutes; adjust to the rules)

| Time | Scene | Screen | Narration points |
| --- | --- | --- | --- |
| 0:00–0:20 | Problem | Title slide + one example of a hidden link | Risk hides in relationships across filings; reading one report at a time misses them |
| 0:20–0:50 | Architecture | `docs/architecture.png` | Filings → verified graph in **TigerGraph** with page-level provenance → three pipelines → evaluation |
| 0:50–1:10 | H1 | Question inspector | All three get simple facts right, with citations |
| 1:10–1:40 | H2 | Inspector + subgraph (optionally the same query in GraphStudio) | RAG retrieved text about each company separately; GraphRAG followed the shared-director link with a GSQL traversal in TigerGraph |
| 1:40–2:15 | H3 | Inspector + agent trace | Agent found the entity, called TigerGraph queries (year-filtered traversal, accumulator total), used the calculator, verifier checked every claim |
| 2:15–2:35 | H4 | Inspector + trace | Where the agent failed and why; the label on the Failures page |
| 2:35–3:15 | Results | Overview + Trade-offs | Who wins per category (with CIs); what the agent costs in time and money |
| 3:15–3:35 | Trust | Data quality panel | Extraction precision, resolution precision, verified gold set, known biases |
| 3:35–3:50 | Close | README + repo URL | One command to run; what you'd do next (query router) |

Write the narration as full sentences in `docs/demo-script.md`, then cut words until it fits.

### Step 4 — Prepare the recording environment

- Run the Compose demo (demo mode on) so nothing depends on live API calls.
- Browser: clean profile, zoom ~110–125% for readability, hide bookmarks bar, close notifications.
- Dashboard: pre-select the final runs; open each hero question in its own tab in order.
- Screen resolution 1920×1080 if possible.
- Microphone test; quiet room.

### Step 5 — Record

1. Record scene by scene (easier to redo).
2. Use a screen recorder you are comfortable with (OBS Studio is a common free option).
3. Keep the mouse still when not pointing at something; zoom or highlight the key element (citation, CI bar, trace step).
4. Edit: cut pauses, add simple captions for key numbers, add chapter titles if the platform supports them.
5. Check audio levels and that text is readable at 720p.

### Step 6 — Review against the brief

Watch the final video and tick:
- [ ] Shows a working Agentic GraphRAG system.
- [ ] Shows answers produced three ways.
- [ ] Shows where each approach succeeds.
- [ ] Shows where each approach fails (including the agent).
- [ ] Shows the metrics dashboard.
- [ ] Shows the architecture.
- [ ] Shows TigerGraph in use (GraphStudio schema/graph view or GSQL query and result) and says what TigerGraph contributes.
- [ ] Every number on screen matches `docs/results.md`.
- [ ] No claims about companies beyond cited facts; neutral wording.
- [ ] Within the time limit.

### Step 7 — Final repository pass

- [ ] README headline table matches `docs/results.md` and the dashboard.
- [ ] Video link in README.
- [ ] Architecture diagram in README and `docs/`.
- [ ] README section on TigerGraph usage: schema, installed queries, vector search mode (native or fallback), TigerGraph version, and how to reproduce.
- [ ] License present.
- [ ] `docs/` contains PRD, TRD, ARCHITECTURE, phases, decisions, data-quality, evaluation, results.
- [ ] Tag the release: `v1.0-submission`.
- [ ] CI green on the tagged commit.
- [ ] Fresh-clone test repeated on the tagged commit.

### Step 8 — Submit

- [ ] GitHub repo URL (public if required).
- [ ] Architecture diagram file.
- [ ] Demo video link/file.
- [ ] Metrics dashboard: screenshots/link as required (and it runs locally via Compose).
- [ ] Any required form fields (team, description, tech stack).
- [ ] Submit before the deadline with margin; keep the confirmation.

---

## 10.4 If time runs short (cut order)

1. Hosted deployment → show the local demo in the video.
2. Global mode / community summaries → keep the statistics pack.
3. FastAPI → dashboard calls pipelines directly.
4. OCR → exclude scanned documents and report the count.
5. Fewer companies → keep at least ~30 so multi-hop questions still exist.

**Never cut:** grounding check, verified test set, fair comparison, failure analysis, honest failure in the video.

---

## 10.5 Pitfalls

| Symptom | Cause | Fix |
| --- | --- | --- |
| Video runs long | Too many features shown | One hero question per point |
| Live call fails during recording | Network/API issue | Demo mode with cached answers |
| Judges can't read the screen | Small fonts | Zoom browser; crop recording |
| Numbers in video differ from repo | Rerun after recording | Record only after the final frozen runs |
| Overclaiming ("the agent is always better") | Enthusiasm | Say "on these question types, in this dataset, with these CIs" |

---

## 10.6 After the hackathon

See `PRD.md` §3.2 and the "Future improvements" ideas: a query router that picks the cheapest pipeline likely to succeed, incremental updates from new filings, more sectors and years, and user feedback flowing into the review queue and evaluation set.
