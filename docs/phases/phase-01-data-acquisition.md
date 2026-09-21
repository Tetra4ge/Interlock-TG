# Phase 1 — Data Acquisition

> **Accuracy note.** I do not give exact download URLs or website APIs for the exchanges or the regulator, because I cannot verify them and they change. This phase tells you how to discover them safely and how to build the code so the URL details live in one small, replaceable module.

---

## 1.1 Overview

| Item | Detail |
| --- | --- |
| Goal | Every target document for the selected companies and years is obtained once, stored immutably under its content hash, and registered with provenance |
| Why | Citations, reproducibility and the evaluation all depend on knowing exactly which file each fact came from |
| Prerequisites | Phase 0 exit criteria; Q-03 (download permission) answered |
| Produces | `config/companies.yaml`, `ingest/` package, populated `documents` and `fetch_attempts` tables, files in `data/raw/`, `docs/coverage.md` |
| PRD links | FR-01 to FR-05, NFR-02, NFR-12 |
| TRD links | §3.3 `fetch`, §4.1 `DocumentMeta`, §5 `documents`, `fetch_attempts` |

---

## 1.2 Concepts you will learn

### Idempotency
An operation is idempotent if running it twice has the same effect as running it once. Here: registering the same PDF twice must create one row and one file. We achieve it by using the SHA-256 hash of the file's bytes as its ID. Identical bytes → identical ID → "already have it, skip".

### Content addressing
Files are stored as `data/raw/<sha256>.pdf`. The name *is* the content fingerprint. Benefits: duplicates are impossible, and if a website silently replaces a file, you store both versions instead of losing the old one.

### Provenance
For each document you record where it came from (URL or "manual"), when, and what it is (company, type, fiscal year). Later, every fact points to a `doc_id`, so any answer can be traced back to its exact source.

### Polite scraping
- Wait between requests (several seconds).
- Identify yourself with a descriptive User-Agent including contact info.
- Respect robots.txt and terms of use.
- Stop on repeated errors instead of hammering the server.

### Selection bias
If you choose only companies known for scandals, the dataset over-represents regulatory actions, multi-hop questions become artificially easy, and the project can look like it targets specific firms. A written, rule-based selection avoids both problems.

---

## 1.3 Files created

```
config/companies.yaml
src/hidden_links/ingest/
├── __init__.py
├── models.py          # CompanyConfig, DocumentTarget, FetchResult
├── registry.py        # register(), exists(), list_documents()
├── inbox.py           # ingest_inbox(): manual files → registry
├── sources/
│   ├── __init__.py
│   ├── base.py        # SourceAdapter protocol
│   ├── exchange.py    # adapter for annual reports / shareholding / RPT filings
│   └── regulator.py   # adapter for regulatory orders
├── fetcher.py         # polite HTTP client + orchestration
└── coverage.py        # expected vs obtained report
tests/unit/test_registry.py
tests/unit/test_inbox_names.py
tests/unit/test_fetcher_retry.py
docs/coverage.md
docs/decisions/0000-scope.md   (updated with selection rule)
```

---

## 1.4 Step-by-step implementation

### Step 1 — Decide sectors, years and the selection rule

1. **Pick 2–3 sectors.** Good choices have:
    - Many related-party transactions (group structures), e.g. sectors dominated by business groups.
    - Enough companies to form cross-company links (shared directors, shared auditors).
    - Mixed company sizes.
2. **Pick 3 consecutive fiscal years.** Use the convention `FY2023-24` everywhere (in config, database, graph and questions). Never mix "FY24", "2023-24" and "2024".
3. **Write the selection rule**, for example:
   > "All companies in sector indices X and Y as of <date>, plus every listed company in those sectors named in a regulator's order dated within the three selected fiscal years, capped at 100 companies."
4. Save the rule in `docs/decisions/0000-scope.md` and at the top of `companies.yaml` as a comment.

Why the second clause: without some companies named in regulatory orders, there are no `NAMED_IN` edges, and whole question categories disappear. Including them *by rule* (not by hand-picking) keeps it fair.

### Step 2 — `companies.yaml` format

```yaml
# Selection rule: <paste rule here>
# Rule applied on: <date>
fiscal_years: ["FY2021-22", "FY2022-23", "FY2023-24"]
doc_types: [annual_report, shareholding, rpt_disclosure]
companies:
  - company_id: "C001"            # internal stable id until CIN is known
    name: "Example Industries Limited"
    exchange_codes: {bse: "500000", nse: "EXAMPLE"}   # fill real codes
    cin: null                     # fill when found in the annual report
    sector: "Sector A"
    selection_reason: "index constituent"   # or "named in order <id>"
  - company_id: "C002"
    ...
```

Rules:
- `company_id` never changes, even if the company is renamed. CIN is added later.
- `selection_reason` makes the selection auditable.

Pydantic models (`ingest/models.py`):

```python
from pydantic import BaseModel

class CompanyConfig(BaseModel):
    company_id: str
    name: str
    exchange_codes: dict[str, str] = {}
    cin: str | None = None
    sector: str
    selection_reason: str

class CompaniesFile(BaseModel):
    fiscal_years: list[str]
    doc_types: list[str]
    companies: list[CompanyConfig]

class DocumentTarget(BaseModel):
    company_id: str | None
    doc_type: str
    fiscal_year: str | None
    period_label: str | None = None   # e.g. quarter for shareholding filings

class FetchResult(BaseModel):
    target: DocumentTarget
    url: str | None
    content: bytes | None
    http_status: int | None
    error: str | None
```

### Step 3 — Understand the sources manually first (no code yet)

For **each** document type, do this by hand for 2–3 companies:

1. Find the document on the official exchange or company website.
2. Record in `docs/sources.md`:
    - The listing page you navigated to.
    - The final PDF URL.
    - Whether the URL follows a predictable pattern.
    - Whether the site loads data through a JSON endpoint visible in the browser's developer tools (Network tab).
    - Whether downloads require cookies or headers.
3. Read the site's **terms of use** and `robots.txt`.
4. Decide per source: **automated** (allowed and predictable) or **manual** (download by hand into the inbox).

Document types to check (**Verify** exact names and filing frequencies on the official sites):

| Doc type | What to look for |
| --- | --- |
| Annual report | The full annual report PDF for each fiscal year |
| Shareholding pattern | Periodic filing showing promoter/public holdings and pledged shares |
| Related-party transaction disclosure | Periodic disclosure of related-party transactions |
| Regulatory orders | The regulator's published orders; searchable by entity name |

If a source is complicated, **go manual**. For 50–100 companies × 3 years, manual download of annual reports is tedious but feasible, and it removes legal and technical risk. Your hackathon is judged on the answering system, not on the scraper.

### Step 4 — Registry (`ingest/registry.py`)

```python
import shutil
from datetime import datetime, timezone
from pathlib import Path
from hidden_links.common.ids import sha256_bytes

RAW = Path("data/raw")

def register(conn, content: bytes, *, company_id, doc_type, fiscal_year,
             source_url: str | None) -> tuple[str, bool]:
    """Store bytes under their hash and insert a documents row.
    Returns (doc_id, created). created=False if it already existed."""
    if not content.startswith(b"%PDF"):
        raise ValueError("not a PDF (missing %PDF header)")
    doc_id = sha256_bytes(content)
    path = RAW / f"{doc_id}.pdf"
    row = conn.execute("SELECT 1 FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    if row:
        return doc_id, False
    RAW.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)
    conn.execute(
        "INSERT INTO documents(doc_id, company_id, doc_type, fiscal_year, source_url, "
        "file_path, fetched_at, status) VALUES (?,?,?,?,?,?,?, 'registered')",
        (doc_id, company_id, doc_type, fiscal_year, source_url, str(path),
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return doc_id, True
```

Notes:
- The `%PDF` check catches HTML error pages saved as `.pdf` — a very common scraping bug.
- If the same bytes are registered for two different companies (it happens with combined filings), the second call returns `created=False`. Log it; handle multi-company documents later via extraction, not duplication.

### Step 5 — Manual inbox (`ingest/inbox.py`)

File naming convention for manual downloads:

```
<company_id>__<doc_type>__<fiscal_year>[__<period>].pdf
examples:
C001__annual_report__FY2023-24.pdf
C001__shareholding__FY2023-24__Q4.pdf
ORDER__regulatory_order__<order-date-YYYY-MM-DD>__<short-slug>.pdf
```

Double underscores avoid clashing with hyphens in fiscal years.

```python
import re
from pathlib import Path

NAME_RE = re.compile(
    r"^(?P<company>[A-Z0-9]+)__(?P<doctype>[a-z_]+)__(?P<fy>FY\d{4}-\d{2}|\d{4}-\d{2}-\d{2})"
    r"(?:__(?P<period>[A-Za-z0-9-]+))?\.pdf$"
)

def parse_name(name: str) -> dict | None:
    m = NAME_RE.match(name)
    return m.groupdict() if m else None

def ingest_inbox(conn, inbox=Path("data/inbox"), processed=Path("data/inbox/processed")):
    processed.mkdir(parents=True, exist_ok=True)
    report = {"registered": 0, "duplicates": 0, "bad_names": []}
    for f in sorted(inbox.glob("*.pdf")):
        meta = parse_name(f.name)
        if meta is None:
            report["bad_names"].append(f.name)
            continue
        company = None if meta["company"] == "ORDER" else meta["company"]
        fy = meta["fy"] if meta["fy"].startswith("FY") else None
        doc_id, created = register(conn, f.read_bytes(), company_id=company,
                                   doc_type=meta["doctype"], fiscal_year=fy,
                                   source_url=None)
        report["registered" if created else "duplicates"] += 1
        f.rename(processed / f.name)
    return report
```

Store the regulatory order's date separately (e.g. in a small `order_meta` JSON sidecar or an extra column) if the filename carries it; you will also extract it in Phase 2.

### Step 6 — Source adapters (`ingest/sources/`)

Keep site-specific logic isolated so a change on a website touches one file.

```python
from typing import Protocol, Iterable
from hidden_links.ingest.models import CompanyConfig, DocumentTarget

class SourceAdapter(Protocol):
    name: str
    def targets(self, company: CompanyConfig, fiscal_years: list[str]) -> Iterable[DocumentTarget]: ...
    def resolve_urls(self, client, target: DocumentTarget) -> list[str]: ...
```

- `targets()` expands config into concrete document targets (e.g. one annual report per year; several shareholding filings per year).
- `resolve_urls()` finds the PDF URL(s) for a target — by pattern, by a listing page, or by a JSON endpoint you discovered in Step 3.

Implement `resolve_urls` **only** after Step 3 confirms the approach is allowed. If not allowed, the adapter returns `[]` and the coverage report tells you which files to download manually.

### Step 7 — Polite fetcher (`ingest/fetcher.py`)

```python
import random, time
import httpx

class PoliteClient:
    def __init__(self, user_agent: str, delay: float, timeout: float, max_retries: int):
        self.client = httpx.Client(headers={"User-Agent": user_agent},
                                   timeout=timeout, follow_redirects=True)
        self.delay, self.max_retries = delay, max_retries
        self._last = 0.0

    def get(self, url: str) -> httpx.Response:
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        backoff = 2.0
        for attempt in range(1, self.max_retries + 1):
            try:
                r = self.client.get(url)
                self._last = time.monotonic()
                if r.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
                return r
            except (httpx.TransportError, httpx.HTTPStatusError):
                if attempt == self.max_retries:
                    raise
                time.sleep(backoff + random.uniform(0, 1))
                backoff *= 2
        raise RuntimeError("unreachable")
```

**Verify** httpx exception class names in its docs.

Orchestration:

```python
def fetch_all(conn, companies_file, adapters, client, log):
    for company in companies_file.companies:
        for adapter in adapters:
            for target in adapter.targets(company, companies_file.fiscal_years):
                if already_have(conn, target):
                    continue
                try:
                    urls = adapter.resolve_urls(client, target)
                except Exception as e:
                    record_attempt(conn, target, None, None, "resolve_failed", str(e))
                    continue
                if not urls:
                    record_attempt(conn, target, None, None, "manual_needed", None)
                    continue
                for url in urls:
                    try:
                        r = client.get(url)
                        doc_id, created = register(conn, r.content, company_id=target.company_id,
                                                   doc_type=target.doc_type,
                                                   fiscal_year=target.fiscal_year, source_url=url)
                        record_attempt(conn, target, url, r.status_code,
                                       "ok" if created else "duplicate", None)
                    except Exception as e:
                        record_attempt(conn, target, url, None, "failed", str(e))
```

`already_have()` checks `documents` for `(company_id, doc_type, fiscal_year)`; for multi-file types (e.g. several shareholding filings per year) include the period.

**Circuit breaker:** if 5 consecutive requests to the same host fail, stop that adapter and log it. This protects both you and the site.

### Step 8 — Regulatory orders

1. For each selected company (and later, each director you resolve in Phase 3), search the regulator's orders for the name. This is often easiest by hand.
2. Save relevant orders into the inbox with the `ORDER__regulatory_order__<date>__<slug>.pdf` name.
3. Keep a list `data/orders_index.csv` with columns: `order_date, regulator, slug, names_searched, source_url`.

Relevance rule: the order names a selected company, or a person who is (or later turns out to be) a director of a selected company. Revisit this list after Phase 3 when you know the directors — this second pass creates many of the interesting multi-hop links.

### Step 9 — Coverage report (`ingest/coverage.py`)

Output `docs/coverage.md`:

| company_id | name | FY2021-22 AR | FY2022-23 AR | FY2023-24 AR | shareholding filings | RPT disclosures | orders |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C001 | Example Industries | ✅ | ✅ | ❌ manual_needed | 11/12 | 5/6 | 1 |

Also print totals: expected, registered, failed, manual_needed. Use this table to plan manual downloads.

### Step 10 — CLI commands

| Command | Action |
| --- | --- |
| `hl fetch [--company C001] [--doc-type annual_report]` | Run adapters (respecting rate limits) |
| `hl ingest-inbox` | Register manual files |
| `hl coverage` | Regenerate `docs/coverage.md` |

---

## 1.5 Data quality checks at this stage

| Check | How |
| --- | --- |
| Every file is a real PDF | `%PDF` header (already in `register`) |
| File opens | Try opening with PyMuPDF; mark `status='failed'` with error if not |
| Page count is plausible | Annual reports are usually long; a 1–2 page "annual report" is probably a cover letter — flag for review |
| Right company | Open 10 random files and check the company name on page 1 |
| Right year | Same spot-check for fiscal year |

Record the spot-check results in `docs/coverage.md`.

---

## 1.6 Tests

| Test | Expectation |
| --- | --- |
| `register` same bytes twice | One row, one file, second returns `created=False` |
| `register` HTML bytes | Raises `ValueError` |
| `parse_name` valid names | Returns correct fields for company/regulatory formats |
| `parse_name` invalid names | Returns `None` |
| `ingest_inbox` | Moves files to `processed/`, reports bad names |
| `PoliteClient` retry | Mock transport returns 503 twice then 200 → success; monkeypatch sleep |
| `PoliteClient` gives up | Always 503 → raises after `max_retries` |
| Delay respected | Two calls with a fake clock → sleep called with ≥ delay |

Use `httpx.MockTransport` for HTTP mocking (**Verify** in httpx docs).

---

## 1.7 Error handling

| Situation | Behavior |
| --- | --- |
| URL returns HTML instead of PDF | Rejected by `%PDF` check; attempt logged as failed |
| Site blocks or rate-limits | Backoff; circuit breaker stops the adapter; switch to manual |
| File corrupted | `status='failed'`; appears in coverage report |
| Duplicate file for different targets | Logged as duplicate; single document kept |
| Bad inbox filename | Listed in report; file left in inbox |

---

## 1.8 Exit criteria

| # | Criterion | How to check |
| --- | --- | --- |
| 1 | Selection rule written and applied | `docs/decisions/0000-scope.md`, `companies.yaml` |
| 2 | All target documents registered, or listed as missing with a reason | `docs/coverage.md` |
| 3 | Rerunning `hl fetch` downloads nothing new | Attempts show `duplicate`/skipped |
| 4 | Spot-check of 10 files passed | Notes in `docs/coverage.md` |
| 5 | Regulatory order index started | `data/orders_index.csv` |
| 6 | Tests pass | `make test` |

---

## 1.9 Pitfalls and debugging

| Symptom | Cause | Fix |
| --- | --- | --- |
| Many tiny "PDFs" | Error pages or login pages saved | `%PDF` check; inspect `fetch_attempts` |
| Wrong year's report | Fiscal-year label confusion | One convention; spot-check page 1 |
| Getting blocked | Too fast / no User-Agent | Increase delay; switch to manual |
| Missing orders for directors | Director names unknown until Phase 3 | Second order search after Phase 3 |
| Huge repo | Committed raw PDFs | Keep `data/raw/` gitignored; commit only small samples later |

---

## 1.10 Hand-off to Phase 2

Phase 2 needs: `documents` rows with `status='registered'` and files in `data/raw/`. It reads them, parses them, and updates `status` to `parsed` / `extracted` / `failed`.
