# ADR 0000: Hackathon Scope & Assumptions

## Context
We need to clearly define the boundaries of the Interlock-TG Agentic GraphRAG project regarding datasets, LLM budget, scraping rules, and entity identification (Q-01 through Q-04).

## Decisions

### 1. Dataset (Q-01)
We will focus exclusively on publicly available Corporate Annual Reports and Governance documents (PDFs) from major companies.

### 1a. Company selection rule (Phase 1)
Rule: *all listed group entities of the Bajaj Group and the Tata Group, as of 2026-09-28,
restricted to entities with at least one full annual report available for each of fiscal
years FY2021-22, FY2022-23 and FY2023-24.*

We picked two business groups rather than unrelated single companies because the project's
whole value proposition (GraphRAG over shared directors, auditors and related-party
transactions) only shows up when the graph actually has cross-company edges. A basket of
unrelated single companies (the original Phase 0 parser-bakeoff sample: NSE, Reliance,
Wipro, Bajaj Finance, Sun Pharma) has almost none. A single business group maximizes edge
density but gives only one sector/governance story; two unrelated groups keep the dataset
auditable (no cherry-picking within a group) while still giving a cross-group contrast in
the demo (e.g. "which directors sit on boards in both groups?" reliably answers "none",
which is itself a useful abstention case).

Selected companies (8 total, `config/companies.yaml`):
- **Bajaj Group:** Bajaj Finance Ltd (BAJFINANCE), Bajaj Finserv Ltd (BAJAJFINSV), Bajaj Auto
  Ltd (BAJAJ-AUTO), Bajaj Holdings & Investment Ltd (BAJAJHLDNG).
- **Tata Group:** Tata Motors Ltd (TATAMOTORS), Tata Steel Ltd (TATASTEEL), Tata Power Co.
  Ltd (TATAPOWER), Tata Consumer Products Ltd (TATACONSUM).

Fiscal years: FY2021-22, FY2022-23, FY2023-24 (three consecutive years, per TRD convention;
never "FY22" or "2021-22" elsewhere in config, DB or graph).

Document types, in priority order:
1. **`annual_report`** — required for every company/year. This is the primary source; per
   ADR-0001 it already contains the board-composition/governance table and the related-party
   transactions annexure, so it alone covers most of what FR-01–FR-05 need.
   2. **`shareholding`**, **`rpt_disclosure`** — optional/best-effort. These are periodic
   filings (quarterly/half-yearly) on the exchange sites, not the company's own investor-relations
   pages; Step 3's source check found them behind bot-detection (see `docs/sources.md`), so
   they are marked `manual_needed` rather than blocking Phase 1 exit. They can be added later
   without touching the schema or the graph model.

Not a hand-picked list: every company in the rule is included, and none are added or dropped
based on how "interesting" their governance history looks, per the selection-bias concern in
the phase doc.

### 2. LLM APIs & Budget (Q-02)
We will use free-tier provider APIs (e.g., Groq) as configured in `models.yaml`, so no paid LLM spend is required. A hard spend limit of **$25.00 USD** is still enforced by our LLM Gateway (`llm_spend_cap_usd`) as a safety net in case a paid provider is swapped in later. Local caching is mandatory during development to minimize free-tier rate-limit pressure.

### 3. Downloading and Scraping (Q-03)
We will only fetch public documents that do not prohibit automated downloading via `robots.txt` or terms of service. Rate limiting (sleeps) will be used when fetching from the same domain.

### 4. Entity Identification (Q-04)
We assume Director Identification Numbers (DINs) or equivalent identifiers (CIN/FRN) will be available in the governance sections of the reports to uniquely merge nodes in the TigerGraph database.
