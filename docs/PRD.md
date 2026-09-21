# PRD — Interlock: Agentic GraphRAG for Corporate Governance Networks

| Field | Value |
| --- | --- |
| Document | Product Requirements Document |
| Product | Interlock |
| Version | 1.0 |
| Status | Draft for build |
| Related | `TRD.md` (how it is built), `ARCHITECTURE.md` (system design), `phases/` (build plan) |

---

## 1. Summary

Interlock is a question-answering system over public disclosures of Indian listed companies. It builds a knowledge graph of companies, directors, shareholders, auditors, related-party transactions and regulatory actions. It then answers natural-language questions three different ways — **RAG**, **GraphRAG** and **Agentic GraphRAG** — and shows, with measured evidence, where each approach succeeds and where it fails.

It is built for a hackathon whose brief requires:

1. A working Agentic GraphRAG system.
2. Answers produced three ways (RAG, GraphRAG, Agentic GraphRAG).
3. A demonstration of where each approach succeeds or fails.
4. **TigerGraph as the graph database.** The hackathon is organised by TigerGraph, so the knowledge graph, graph traversal and (if the installed version supports it) vector search must run on TigerGraph, queried with GSQL.
5. Submission of a GitHub repo, architecture diagram, demo video and metrics dashboard.

This is a standalone project. It shares no code, data or components with any other project.

---

## 2. Problem

### 2.1 Problem statement

Governance risk in listed companies often lives in **relationships between disclosures**, not inside any single document:

- A director sits on the boards of several companies, one of which was named in a regulatory order.
- A promoter's stake is pledged, and the promoter group also holds stakes through subsidiaries.
- A company records large related-party transactions with an entity whose directors overlap with its own board.
- A company changes auditors shortly after a regulatory action.

Each fact is disclosed publicly, but across different documents (annual reports, shareholding filings, related-party disclosures, regulatory orders), different years, and inconsistent formats.

### 2.2 Who experiences it

| Persona | Need | Current workaround |
| --- | --- | --- |
| Retail investor | Understand governance red flags before investing | Reads a few annual reports; misses indirect links |
| Equity research analyst | Map board/ownership networks quickly | Manual spreadsheets; paid databases |
| Proxy advisor / governance researcher | Evaluate director independence and interlocks | Manual cross-checking across filings |
| Financial journalist | Trace connections behind a story | Days of document reading |
| Compliance / due-diligence analyst | Screen counterparties | Paid tools, manual review |

For the hackathon, the **primary audience is the judges**. They need to see a working system, understand the comparison in minutes, and trust the numbers.

### 2.3 Why existing approaches fall short

- **Keyword search** finds documents that mention a name but cannot follow chains.
- **Plain RAG** retrieves text chunks similar to the question. It cannot reliably join facts spread across several documents, and it cannot compute totals over many values.
- **Paid databases** exist but are not open, not explainable, and not question-driven.

### 2.4 Proposed solution

1. Extract facts from public filings into a typed, time-aware knowledge graph. Every fact is linked to its source document, page and exact quote.
2. Provide three answering pipelines over the same data and the same LLM:
    - **RAG:** vector search over text chunks, one LLM call.
    - **GraphRAG:** entity linking, bounded subgraph retrieval plus linked text, one LLM call.
    - **Agentic GraphRAG:** an agent that plans, calls graph/text/calculation tools step by step, and verifies its answer before responding.
3. Evaluate all three on a fixed, verified question set across six question types, and show accuracy, faithfulness, cost, latency and failure types on a dashboard.

---

## 3. Goals

### 3.1 Primary goals (must ship)

| ID | Goal | Measure of success |
| --- | --- | --- |
| G-1 | Verified knowledge graph | 50–100 companies, 2–3 sectors, 3 fiscal years; every fact edge has document + page + quote; extraction precision measured and reported |
| G-2 | Three comparable pipelines | Same LLM, corpus, answer rules and output format; all three answer every test question |
| G-3 | Verified evaluation set | 150–300 questions, 6 categories, gold answers checked against source PDFs, frozen dev/test split |
| G-4 | Honest comparison | Per-category accuracy with confidence intervals, cost, latency, failure taxonomy for each pipeline |
| G-5 | Metrics dashboard | Five pages (Overview, Trade-offs, Failures, Question inspector, Live ask) |
| G-6 | Submission deliverables | GitHub repo, architecture diagram, demo video, metrics dashboard |

### 3.2 Secondary goals (after primary goals are met)

| ID | Goal |
| --- | --- |
| SG-1 | Interactive graph explorer highlighting the subgraph used in an answer |
| SG-2 | Community summaries for corpus-wide ("global") questions |
| SG-3 | Streaming agent steps in the live UI |
| SG-4 | Public hosted demo |
| SG-5 | Additional sectors or years via configuration only |
| SG-6 | Small external benchmark subset to show generalization |

### 3.3 Non-goals

| ID | Non-goal | Reason |
| --- | --- | --- |
| NG-1 | Investment advice, buy/sell signals, price prediction | Out of scope; legal and ethical risk |
| NG-2 | Real-time market data or trading | Not needed for the brief |
| NG-3 | User accounts, multi-tenancy, billing | Single-user demo |
| NG-4 | Coverage of all listed companies | Quality over breadth |
| NG-5 | Fine-tuning or training models | Not needed; adds time and cost |
| NG-6 | Risk scores or conclusions about wrongdoing | System reports disclosed facts with citations only |

---

## 4. Users and use cases

### 4.1 User stories

| ID | As a… | I want to… | So that… |
| --- | --- | --- | --- |
| US-01 | Judge | See at a glance which pipeline wins on which question type | I understand the result in under a minute |
| US-02 | Judge | Open one question and compare all three answers with evidence | I can trust the claims |
| US-03 | Judge | See where the agent fails and what it costs | I see an honest evaluation |
| US-04 | Judge | Ask my own question and see three answers | I can test the system myself |
| US-05 | Analyst | Ask "which companies share directors with firms named in regulatory orders?" | I find interlock quickly |
| US-06 | Analyst | Click a citation and see the exact source page and quote | I can verify every claim |
| US-07 | Developer | Rebuild the whole graph from raw files with one command | Results are reproducible |
| US-08 | Developer | Run the full evaluation with one command | I can compare changes reliably |
| US-09 | Developer | Review extraction errors in a queue | I can fix data problems |

### 4.2 Example questions the product must handle

| Category | Example |
| --- | --- |
| Single-fact | Who was the statutory auditor of Company X in FY2023-24? |
| Multi-hop | Which companies in the dataset share at least one independent director with a company named in a regulatory order? |
| Temporal | Which directors joined Company X's board after it was named in a regulatory order? |
| Numerical | What was the total value of related-party transactions between Company X and promoter-group entities in FY2022-23, in ₹ crore? |
| Global | Which sector in the dataset had the most auditor changes across the three years? |
| Unanswerable | What is the CEO's salary for FY2030? (must answer "not found in the data") |

---

## 5. Functional requirements

Priority: **P0** = must ship; **P1** = should ship; **P2** = nice to have.

### 5.1 Data acquisition

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-01 | The system shall download filings (annual reports, shareholding patterns, related-party disclosures) for a configured list of companies and fiscal years. | P0 |
| FR-02 | The system shall collect regulatory orders that name selected companies or their directors. | P0 |
| FR-03 | The system shall store each raw file exactly once, identified by its SHA-256 hash, with source URL and download time. | P0 |
| FR-04 | The system shall accept manually downloaded files placed in an inbox folder. | P0 |
| FR-05 | The system shall produce a coverage report of expected vs obtained documents. | P1 |

### 5.2 Processing

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-06 | The system shall extract text per page, preserving page numbers. | P0 |
| FR-07 | The system shall extract tables with row/column structure. | P0 |
| FR-08 | The system shall detect target sections (governance report, related-party note, auditor's report, board's report, subsidiaries). | P0 |
| FR-09 | The system shall split text into chunks carrying document, company, year, section and page range. | P0 |
| FR-10 | The system shall extract entities and relations into typed records, each with an evidence quote and page. | P0 |
| FR-11 | The system shall reject records whose evidence quote is not found on the stated page. | P0 |
| FR-12 | The system shall validate records against format, range, consistency and unit rules. | P0 |
| FR-13 | The system shall send failing records to a review queue with a reason. | P0 |
| FR-14 | The system shall provide a review UI to accept, fix or reject queued records. | P1 |

### 5.3 Knowledge graph

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-15 | The system shall resolve mentions to canonical entities using DIN/CIN/auditor registration numbers first, fuzzy matching second. | P0 |
| FR-16 | The system shall log every merge decision with method, score and reason. | P0 |
| FR-17 | The system shall load entities and relations into TigerGraph (schema defined in GSQL) with time and value properties. | P0 |
| FR-18 | The system shall attach provenance (document, page, quote, extraction run) to every fact edge. | P0 |
| FR-19 | The system shall store chunk embeddings in a vector index linked to the entities they mention. | P0 |
| FR-20 | The system shall rebuild the complete graph from raw files with one command. | P0 |

### 5.4 Question answering

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-21 | The system shall answer questions using the RAG pipeline. | P0 |
| FR-22 | The system shall answer questions using the GraphRAG pipeline. | P0 |
| FR-23 | The system shall answer questions using the Agentic GraphRAG pipeline. | P0 |
| FR-24 | All pipelines shall return the same `AnswerResult` structure (answer, type, citations, evidence, trace, usage, status). | P0 |
| FR-25 | All pipelines shall answer "not found in the data" when evidence does not support an answer. | P0 |
| FR-26 | The agent shall never execute graph write operations. | P0 |
| FR-27 | The agent shall stop within configured step, token and time budgets. | P0 |
| FR-28 | The system shall answer global questions using community summaries. | P2 |

### 5.5 Evaluation

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-29 | The system shall store a versioned question set with category, gold answer, gold evidence and split. | P0 |
| FR-30 | The system shall run any pipeline over any split with one command. | P0 |
| FR-31 | The system shall score correctness, faithfulness, citation accuracy, evidence recall, abstention, latency, tokens and cost. | P0 |
| FR-32 | The system shall label each wrong answer with one failure type. | P0 |
| FR-33 | The system shall record run config, model versions and git commit for every run. | P0 |
| FR-34 | The system shall compute confidence intervals for per-category accuracy. | P1 |

### 5.6 Presentation

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-35 | The dashboard shall show accuracy by category per pipeline. | P0 |
| FR-36 | The dashboard shall show cost and latency trade-offs. | P0 |
| FR-37 | The dashboard shall show failure types per pipeline. | P0 |
| FR-38 | The dashboard shall show one question's three answers side by side with evidence and agent trace. | P0 |
| FR-39 | The dashboard shall accept a live question and show three answers. | P1 |
| FR-40 | The dashboard shall display the highlighted subgraph used for an answer. | P2 |

---

## 6. Non-functional requirements

| ID | Quality | Requirement | Priority |
| --- | --- | --- | --- |
| NFR-01 | Correctness | Extraction precision measured on a hand-labeled sample and reported per record type | P0 |
| NFR-02 | Reproducibility | Same config + cached LLM responses reproduce identical metrics | P0 |
| NFR-03 | Traceability | Every answer claim maps to document + page | P0 |
| NFR-04 | Fairness | Same answer LLM, temperature, rules and approximately equal evidence budget across pipelines | P0 |
| NFR-05 | Security | No secrets in the repo; agent graph access is read-only; retrieved text never treated as instructions | P0 |
| NFR-06 | Cost | Total LLM spend stays under a configured cap; every call cached | P0 |
| NFR-07 | Observability | Every LLM and tool call recorded with tokens, cost, latency and errors | P0 |
| NFR-08 | Usability | A judge finds the headline result within 1 minute and completes a question inspection within 3 minutes | P0 |
| NFR-09 | Portability | Fresh clone to running demo with `docker compose up` on another machine | P0 |
| NFR-10 | Latency | RAG and GraphRAG answer in seconds in the demo; agent latency reported, not hidden | P1 |
| NFR-11 | Maintainability | Typed models, module boundaries per `ARCHITECTURE.md`, tests on core logic | P1 |
| NFR-12 | Extensibility | New companies, sectors or years added through config only | P1 |
| NFR-13 | Privacy | Only publicly disclosed information stored | P1 |
| NFR-14 | Scalability / availability | Single machine; no high-availability requirement | P2 |

Exact latency and cost numbers are set after the first baseline run, because they depend on the chosen LLM and corpus size.

---

## 7. Success metrics

### 7.1 Product metrics (reported in the submission)

| Metric | Target |
| --- | --- |
| Extraction precision (directors, auditors) | Team-defined bar, suggested ≥ 90%, measured on hand-labeled pages |
| Entity-resolution precision | Reported on a hand-checked sample of 100 decisions |
| Gold-answer verification | 100% of test questions checked against PDFs (minimum 30% if time-constrained, disclosed) |
| Pipeline coverage | All three pipelines return a valid `AnswerResult` for 100% of test questions |
| Comparison clarity | Each category shows a measurable difference between pipelines, or an explained lack of one |

### 7.2 Hackathon success

- All four deliverables submitted.
- TigerGraph is visibly central: the graph lives in TigerGraph, GraphRAG and the agent traverse it with GSQL queries, and the submission explains why a native graph engine helps on multi-hop questions.
- Demo video shows at least one question where each pipeline behaves differently, plus one honest agent failure.
- Repository starts with one command on a clean machine.

---

## 8. Scope and release plan

| Release | Contents | Phases |
| --- | --- | --- |
| R0 — Foundations | Environment, LLM gateway, parser choice | 0 |
| R1 — Data | Downloaded corpus, extraction pilot, full graph | 1–3 |
| R2 — Baseline + Eval | RAG pipeline, evaluation set and runner | 4–5 |
| R3 — Comparison | GraphRAG, Agentic GraphRAG | 6–7 |
| R4 — Presentation | API, dashboard, hardening | 8–9 |
| R5 — Submission | Demo video, final checks | 10 |

### Cut order if time runs short

1. Hosted deployment (use a local demo in the video).
2. Global mode / community summaries.
3. FastAPI (dashboard calls pipelines directly).
4. OCR support (exclude scanned documents; report the count).
5. Number of companies (keep at least 30).

**Never cut:** grounding check, verified test set, fair comparison, failure analysis.

---

## 9. Assumptions

| ID | Assumption |
| --- | --- |
| A-01 | The team may choose its own domain and data. |
| A-02 | Paid LLM APIs are allowed within a modest budget. |
| A-03 | Development runs on one laptop; optional small VM for hosting. |
| A-04 | Filings are publicly downloadable; terms of use to be confirmed. |
| A-05 | English-language filings only. |
| A-06 | Judges value working software and honest metrics over feature count. |
| A-07 | Timeline and team size are not fixed; phases use exit criteria instead of dates. |

## 10. Open questions

| ID | Question | Impact if the answer differs from assumption |
| --- | --- | --- |
| Q-01 | Does the "core challenge" specify a dataset or domain? | If yes: replace Phases 1–3 (data and schema); pipelines, evaluation and dashboard stay. |
| Q-02 | Are paid LLM APIs allowed; what is the budget? | If no: local open-weight models; smaller eval set; lower extraction quality expected. |
| Q-03 | Do exchange/regulator sites allow automated download? | If no: manual inbox path only. |
| Q-04 | Are director identification numbers available in filings? | If no: fuzzy resolution with lower, reported precision. |
| Q-05 | Must the demo be publicly hosted? | If yes: add VM deployment in Phase 9. |
| Q-06 | Is a specific metric or benchmark required? | If yes: add it to the scorers first. |
| Q-07 | Are there sponsor LLM providers? | If yes: set as default model in config; no redesign. |
| Q-08 | Which TigerGraph deployment do we use (TigerGraph Savanna cloud, or Community/Developer edition in Docker) and does that version support native vector attributes? | If no vector support: keep chunk embeddings in a local index (FAISS or NumPy) keyed by `chunk_id`, and keep everything else in TigerGraph. |
| Q-09 | Does the hackathon provide a TigerGraph instance, credits or required starter kit/GraphRAG repo? | If yes: use it as the default environment; adapt Phase 0 setup only. |

---

## 11. Risks

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| Extraction quality too low | Medium | High | Section-targeted extraction, grounding check, rule-based tables, pilot on 5 companies |
| Download blocked / not permitted | Medium | Medium | Manual inbox path |
| Director IDs unavailable | Medium | Medium | Extract from report text; fuzzy fallback |
| LLM cost overrun | Medium | Medium | Cache, spend cap, pilot cost projection |
| Wrong gold answers | Medium | High | PDF verification; data-error label |
| Evaluation biased toward GraphRAG | High | Medium | PDF verification; disclose bias |
| Agent unreliable during demo | Medium | High | Budgets, verifier, cached demo answers, recorded video |
| Misrepresenting real companies | Low | High | Cited facts only; neutral wording; no scores |
| Scope creep | High | Medium | Non-goals; cut order |
| TigerGraph learning curve (GSQL, schema changes need a schema-change job) | High | Medium | Phase 0 spike; freeze the schema early; keep queries in versioned `.gsql` files |
| TigerGraph vector or free-tier limits (memory, storage, version) | Medium | Medium | Check limits in Phase 0; fallback local vector index; small sample graph for the demo |

---

## 12. Legal and ethical considerations

- Use only publicly disclosed information.
- Respect website terms of use and rate limits.
- Present facts with citations; never label a company or person as fraudulent or risky.
- Include a disclaimer in the UI and README: "For research and demonstration only. Not investment advice. Facts are extracted automatically and may contain errors; verify against the cited source."

## 13. Glossary

| Term | Meaning |
| --- | --- |
| RAG | Retrieval-Augmented Generation: retrieve text, then generate an answer |
| GraphRAG | RAG that retrieves from a knowledge graph (entities and relations) as well as text |
| Agentic GraphRAG | An LLM agent that decides step by step which graph/text/calculation tools to use |
| DIN | Director Identification Number |
| CIN | Corporate Identity Number |
| Related-party transaction | A transaction between a company and a party connected to it (e.g. promoters, directors, group companies) |
| Promoter | The founding/controlling shareholder group of an Indian listed company |
| Pledge | Shares given as collateral for a loan |
| Provenance | The record of where a fact came from (document, page, quote) |
| Grounding check | Code verifying that an extracted fact's quote actually appears in the source page |
| Gold answer | The verified correct answer used for scoring |
