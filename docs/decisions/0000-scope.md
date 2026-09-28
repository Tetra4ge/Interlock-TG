# ADR 0000: Hackathon Scope & Assumptions

## Context
We need to clearly define the boundaries of the Interlock-TG Agentic GraphRAG project regarding datasets, LLM budget, scraping rules, and entity identification (Q-01 through Q-04).

## Decisions

### 1. Dataset (Q-01)
We will focus exclusively on publicly available Corporate Annual Reports and Governance documents (PDFs) from major companies.

### 2. LLM APIs & Budget (Q-02)
We will use paid provider APIs (e.g., OpenAI / Anthropic) as configured in `models.yaml`. A hard spend limit of **$25.00 USD** is enforced by our LLM Gateway (`llm_spend_cap_usd`). Local caching is mandatory during development to preserve this budget.

### 3. Downloading and Scraping (Q-03)
We will only fetch public documents that do not prohibit automated downloading via `robots.txt` or terms of service. Rate limiting (sleeps) will be used when fetching from the same domain.

### 4. Entity Identification (Q-04)
We assume Director Identification Numbers (DINs) or equivalent identifiers (CIN/FRN) will be available in the governance sections of the reports to uniquely merge nodes in the TigerGraph database.
