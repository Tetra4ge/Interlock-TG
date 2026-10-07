# Document coverage

| company_id | name | FY2021-22 AR | FY2022-23 AR | FY2023-24 AR | shareholding filings | RPT disclosures | orders |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TATAMOTORS | Tata Motors Limited | ✅ | ✅ | ✅ | 0 | 0 | 2 |
| BAJFINANCE | Bajaj Finance Limited | ✅ | ✅ | ✅ | 0 | 0 | 0 |
| TATASTEEL | Tata Steel Limited | ✅ | ✅ | ✅ | 0 | 0 | 2 |
| TRF | TRF Limited | ❌ manual_needed | ❌ manual_needed | ❌ manual_needed | 0 | 0 | 0 |
| BAJAJFINSV | Bajaj Finserv Limited | ✅ | ✅ | ✅ | 0 | 0 | 0 |

## Totals

- Registered documents: 26
- Fetch attempts by outcome: manual_needed=354

## Spot-check notes

10 of the 26 registered documents were picked at random (`random.seed(7)`) and opened with
PyMuPDF to check the company name and fiscal year against what `documents.company_id` and
`documents.fiscal_year` record. All 10 matched.

| doc_id (short) | company_id | fiscal_year | Found on page | Text |
| --- | --- | --- | --- | --- |
| `e9ef5978f631` | BAJFINANCE | FY2022-23 | 2 (cover is a graphic) | "CORPORATE OVERVIEW \| About Bajaj Finance ..." |
| `6f2d3e262def` | BAJAJFINSV | FY2022-23 | 1 | "16th ANNUAL REPORT 2022-2023" |
| `4122214c4bbe` | TATACONSUM | FY2021-22 | 1 | "INTEGRATED ANNUAL REPORT 2021-22" |
| `019618ee1daf` | TATAPOWER | FY2023-24 | 1 | "Integrated Annual Report 2023-24" |
| `fbbfef92873b` | BAJAJ-AUTO | FY2022-23 | 3 (cover + TOC graphic) | "BAJAJ AUTO LIMITED \| 16th ANNUAL REPORT 2022-23" |
| `e13350910bd9` | BAJAJ-AUTO | FY2023-24 | 1 | "BAJAJ AUTO LIMITED \| ANNUAL REPORT 2023-24" |
| `db02424e0ed1` | TATAMOTORS | FY2023-24 | 1 | "79TH INTEGRATED ANNUAL REPORT 2023-24" |
| `6ee1fe59af7d` | BAJAJFINSV | FY2021-22 | 1 | "15TH ANNUAL REPORT 2021-2022 \| BAJAJ FINSERV LIMITED" |
| `a96825481f58` | BAJFINANCE | FY2023-24 | 2 (cover is a graphic) | "CORPORATE OVERVIEW \| About Bajaj Finance \| FY2024 Highlights" |
| `0bd9b1b2d7c3` | TATASTEEL | FY2021-22 | 2 (cover is a graphic) | "Responsible Growth. Sustainable Future. \| In our nearly 12-decade journey ..." |

4 of the 10 have an image-only cover page (no extractable text), so the check used the next page
carrying text. That doesn't affect extraction, which works from detected sections, not page 1.

Note: the registered 26 documents also cover BAJAJ-AUTO, BAJAJHLDNG, TATACONSUM and TATAPOWER —
companies outside the 5-company pilot list in `config/companies.yaml` — most of them marked
`excluded` in `documents.status` and not part of the extraction/graph pipeline.
