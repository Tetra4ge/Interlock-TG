# ADR 0001: PDF Parser Selection

## Context
Phase 0 requires picking a PDF parser from evidence, not assumption. We ran the bake-off
spike (`spikes/parser_bakeoff.py`) against 5 real, unrelated Indian company annual reports,
downloaded into `data/inbox/` and listed with their license/source status in
`docs/decisions/0000-scope.md` (Q-03):

| Report | Pages | Governance table page | RPT page |
| --- | --- | --- | --- |
| NSE Integrated Annual Report FY24 | 210 | 60 (Key Management Personnel) | 67 (Form AOC-2 annexure) |
| Reliance Industries Integrated Annual Report 2023-24 | 159 | 37 (Committee composition) | 133 (Related-party balances) |
| Wipro Annual Report FY23 | 457 | 133 (Board of Directors — DIN table) | 231 (Related-party transactions) |
| Bajaj Finance Annual Report FY2022 | 505 | 75 (Board composition & attendance) | 242 (Related-party transactions note) |
| Sun Pharma Annual Report FY23 | 309 | 64 (Board meetings & attendance) | 192 (Related-party transactions note) |

Exact page picks and file paths are in `spikes/pages.yaml`. Both PyMuPDF (`fitz`, raw text
and `find_tables()`) and pdfplumber (`extract_text()` and `extract_tables()`) were run
against all 10 pages; raw output for every page/parser combination is saved under
`spikes/bakeoff_output/` for inspection.

## Findings

**Reading order / row cohesion (decisive).** On every governance table tested (NSE, Wipro,
Bajaj, Sun Pharma), PyMuPDF's `get_text("text")` shreds each table cell onto its own line
with no row structure at all — e.g. on the Wipro board table, `"Ireena Vittal"`,
`"(DIN: 05195656)"`, `"None"`, `"Independent"`, `"Director"`, `"1-Oct-2013"` each land on a
separate line, in a sequence that requires guessing column identity from position.
pdfplumber's `extract_text()` reliably keeps each director's full row together on one line
(e.g. `"Sanjiv Bajaj Brother of Rajiv Bajaj 530,792 6 6 100"`), even though its own
multi-line column *headers* often garble no better than PyMuPDF's. For LLM-based
extraction — where a director's name, DIN, category and attendance need to stay
attributable to each other — this difference is decisive on its own.

**Neither tool's automatic table-detection API is reliable on these documents.**
`find_tables()` (PyMuPDF) and `extract_tables()` (pdfplumber) both failed to detect a table
at all on 3 of 5 governance pages (NSE, Wipro, Bajaj, Sun Pharma governance). Where both did
detect a table (Reliance's related-party note, a wide table with company names on the left
and multiple year columns), PyMuPDF's table kept the company names but dropped nearly all
the numeric columns; pdfplumber's table kept the numbers but dropped nearly all the company
names — each lost a different half of the same table. Neither `find_tables()` nor
`extract_tables()` can be trusted as the primary signal for these documents; this
contradicts our pre-bake-off assumption that pdfplumber's table API "explicitly models grid
structures" well enough to lean on directly.

**Speed.** Averaged across all 10 pages: PyMuPDF 182.7ms/page vs pdfplumber 274.7ms/page —
pdfplumber is about 34% slower. Real, but small next to the reading-order gap above.

**Numbers/page-index.** No merged-digit or decimal-point corruption observed in either
tool's text output on any sample; both report the same 1-based page index as the PDF
viewer.

## Decision
We reject the pre-bake-off assumption ("PyMuPDF for text, pdfplumber for tables") in favor
of what the evidence actually shows:

1. **pdfplumber's `extract_text()` is the primary text source fed to the extractor LLM**
   for governance and financial-note pages (board composition, RPT, related pages) — its
   row-cohesion is what a downstream LLM needs to correctly attribute values to a director
   or counterparty.
2. **PyMuPDF remains the fast path for prose-only pages** (narrative sections, MD&A) where
   no table exists to lose structure from, and for cheap operations like page counting and
   locating candidate pages by keyword search (as used to build `pages.yaml` itself).
3. **Neither library's structured table API (`find_tables()`/`extract_tables()`) is used as
   a primary signal.** Table geometry, where needed, is reconstructed by the LLM extractor
   from pdfplumber's row-cohesive text rather than trusted from either tool's own table
   detector.

## Consequences
- `Phase 2: Parse` routes governance/financial-note pages to `pdfplumber.extract_text()`,
  not PyMuPDF, reversing the original plan.
- The ~34% per-page speed cost of pdfplumber is accepted for the pages that need it, since
  it is paid only on the smaller subset of table-bearing pages, not the whole document.
- If a future document type shows PyMuPDF's `find_tables()` reliably outperforming this
  baseline (e.g. simpler, single-column tables), re-run `spikes/parser_bakeoff.py` against
  a sample of that document type before changing the routing rule — this decision is
  evidenced for board-composition/RPT tables in Indian annual reports specifically, not a
  general claim about either library.
