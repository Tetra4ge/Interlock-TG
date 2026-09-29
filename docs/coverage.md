# Document coverage

| company_id | name | FY2021-22 AR | FY2022-23 AR | FY2023-24 AR | shareholding filings | RPT disclosures | orders |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BAJFINANCE | Bajaj Finance Limited | ✅ | ✅ | ✅ | 0 | 0 | 0 |
| BAJAJFINSV | Bajaj Finserv Limited | ✅ | ✅ | ✅ | 0 | 0 | 0 |
| BAJAJ-AUTO | Bajaj Auto Limited | ✅ | ✅ | ✅ | 0 | 0 | 0 |
| BAJAJHLDNG | Bajaj Holdings & Investment Limited | ✅ | ✅ | ✅ | 0 | 0 | 0 |
| TATAMOTORS | Tata Motors Limited | ✅ | ✅ | ✅ | 0 | 0 | 2 |
| TATASTEEL | Tata Steel Limited | ✅ | ✅ | ✅ | 0 | 0 | 0 |
| TATAPOWER | Tata Power Company Limited | ✅ | ✅ | ✅ | 0 | 0 | 0 |
| TATACONSUM | Tata Consumer Products Limited | ✅ | ✅ | ✅ | 0 | 0 | 0 |

## Totals

- Registered documents: 24
- Fetch attempts by outcome: manual_needed=240

## Spot-check notes

10 files chosen at random (`random.seed(42)`) from the 24 registered `annual_report` documents,
opened with PyMuPDF and checked for the company's legal name and the fiscal year appearing
within the first few pages (cover, table of contents, chairman's letter).

| company_id | fiscal_year | Company name found | Fiscal year found | Result |
| --- | --- | --- | --- | --- |
| TATAPOWER | FY2023-24 | "Tata Power" (p1, "Integrated Annual Report 2023-24") | "2023-24" (p1) | PASS |
| BAJAJFINSV | FY2021-22 | "Bajaj Finserv Limited" (p1) | "2021-2022" (p1, "15th Annual Report") | PASS |
| BAJAJ-AUTO | FY2021-22 | "Bajaj Auto Limited" (p1) | "2021-22" (p1) | PASS |
| BAJAJHLDNG | FY2023-24 | "79th Annual Report" (p1, matches BHIL's 79th AGM) | "2023-2024" (p1) | PASS |
| BAJAJHLDNG | FY2022-23 | "Bajaj Holdings" (found within first 8 pages) | "2022-23" (contents page) | PASS |
| TATAPOWER | FY2022-23 | "The Tata Power Company Limited" (p1) | "2022-23" (p1) | PASS |
| BAJAJFINSV | FY2022-23 | "Bajaj Finserv" (p1, "16th Annual Report") | "2022-2023" (p1) | PASS |
| TATASTEEL | FY2022-23 | "Tata Steel" (p1, "116th year") | "2022-23" (p1) | PASS |
| BAJAJ-AUTO | FY2023-24 | "Bajaj Auto Limited" (p1) | "2023-24" (p1) | PASS |
| BAJFINANCE | FY2021-22 | "Bajaj Finance" (found within first 8 pages; p1 shows "35th Annual Report" matching BFL's 35th AGM) | "2021-2022" (p1) | PASS |

**Result: 10/10 PASS.** No mismatches found.

Note on `BAJFINANCE__annual_report__FY2021-22.pdf`: the first URL tried for this file
(`bajajfinserv.in/finance-digital-annual-report-fy22/finance-digital-annual-report-assets/pdf/Annual-Report-for-FY2022.pdf`)
downloaded completely (matched `Content-Length`) but the PDF itself was corrupt
(`pdfminer`/`pymupdf` both failed to parse it, 0 pages) -- an apparently broken asset on
the source CDN, not a download error on our end. Recovered via an alternate CMS-hosted URL
(`cms-assets.bajajfinserv.in/is/content/bajajfinance/annual-report-for-fy-2022pdf`), which
parses cleanly at 390 pages.
