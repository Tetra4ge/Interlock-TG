# Document sources (Phase 1, Step 3)

Manual source-check, done before writing any adapter code, per the phase doc's rule:
"if a source is complicated, go manual."

## Annual reports (company investor-relations pages)

Not checked page-by-page in this pass (no live browser session available in this
environment). Annual report PDFs are normally published on each company's own
investor-relations page (e.g. `bajajfinserv.in`, `tatamotors.com`) as a direct PDF link
per fiscal year, not behind a scraping-hostile exchange gateway. Decision for this phase:
**manual** — download by hand into `data/inbox/` using the naming convention in
`ingest/inbox.py`, and verify each site's terms of use at download time. Revisit as
`ingest/sources/exchange.py` (currently a stub returning `[]`) once URL patterns for a
company's IR page are confirmed by hand.

## Shareholding pattern / RPT disclosure (exchange filings)

These are periodic filings hosted on the exchanges (BSE/NSE), not on company IR pages.

- **Attempted:** `curl` to `https://www.nseindia.com/` from this environment.
- **Result:** connection failed at the TLS/HTTP2 layer (`HTTP/2 stream 1 was not closed
  cleanly: INTERNAL_ERROR`) before any content was served — consistent with NSE's known
  bot/anti-scraping posture (it commonly requires browser-realistic TLS fingerprints and
  session cookies obtained by first loading the HTML page). A plain `curl` (confirmed
  working against other sites, e.g. `google.com` returned `HTTP 200`) could not get past
  it.
- **robots.txt / terms of use:** not reviewed yet, since the connection itself failed —
  do this by hand before attempting anything automated here.
- **Decision:** **manual** for this phase. `ingest/sources/exchange.py`'s
  `resolve_urls()` returns `[]` for these doc types, which the fetcher records as
  `manual_needed` in `fetch_attempts` and surfaces in `docs/coverage.md`. This is a
  best-effort/optional doc type for Phase 1 (see `docs/decisions/0000-scope.md` §1a) —
  annual reports already carry the governance and related-party-transaction
  information these filings would add (per ADR-0001), so this does not block the
  exit criteria.

## Regulatory orders

Not checked in this pass. Handled entirely by hand per the phase doc (Step 8): search
the regulator's order database by company/director name, save relevant PDFs into
`data/inbox/` as `ORDER__regulatory_order__<date>__<slug>.pdf`, and track them in
`data/orders_index.csv`. A second pass happens after Phase 3 once director names are
known from extraction.

### Regulatory orders — Phase 1 search result (2026-09-29)

Searched sebi.gov.in (robots.txt allows crawling; order pages fetched by hand at low rate)
for orders dated within FY2021-22 to FY2023-24 that name a selected company. Registered:

- 2022-02-14 — Adjudication order, Bhushan Steel Ltd (now Tata BSL Ltd, merged into Tata Steel) → `TATASTEEL`
- 2022-08-30 — Adjudication order, Usha Martin Ltd and Tata Steel Long Products Ltd (merged into Tata Steel) → `TATASTEEL`

The Tata Motors orders (2017, 2018) are indexed for context but fall outside the FY range and are
not registered as documents.

**No in-range order found** for: Bajaj Finance, Bajaj Finserv, Bajaj Auto, Bajaj Holdings,
Tata Power, Tata Consumer. (Bajaj Auto appears in a 2020 UPSI-leak order against third parties,
out of range; Bajaj Finserv has only 2024 informal guidance, which is not an enforcement order.)
This is a real finding, not a gap to fill: those companies simply have no `NAMED_IN` edges.
The search is repeated after Phase 3 once director names are known.

## Placeholders for unavailable data

Shareholding and RPT-disclosure filings are on bot-protected exchange sites (see above). They
stay `manual_needed` in `fetch_attempts`; no placeholder documents are created, so nothing
downstream mistakes an empty file for real data. Phase 2 draws related-party and pledge
information from the annual reports instead (ADR-0001).
