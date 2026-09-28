import csv
from pathlib import Path

import yaml

from server.ingest.models import CompaniesFile
from server.ingest.registry import list_documents
from server.ingest.sources.regulator import ORDERS_INDEX
from server.store.db import connect

COMPANIES_YAML = Path("config/companies.yaml")
COVERAGE_MD = Path("docs/coverage.md")


def _load_companies_file(path: Path = COMPANIES_YAML) -> CompaniesFile:
    return CompaniesFile(**yaml.safe_load(path.read_text()))


def _latest_attempt_outcome(company_id: str, doc_type: str, fiscal_year: str) -> str | None:
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT outcome FROM fetch_attempts
            WHERE company_id IS ? AND doc_type=? AND fiscal_year IS ?
            ORDER BY attempted_at DESC LIMIT 1
            """,
            [company_id, doc_type, fiscal_year],
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _order_count_for(company_id: str, company_name: str) -> int:
    if not ORDERS_INDEX.exists():
        return 0
    needle_id, needle_name = company_id.lower(), company_name.lower()
    count = 0
    with ORDERS_INDEX.open(newline="") as f:
        for row in csv.DictReader(f):
            searched = (row.get("names_searched") or "").lower()
            if needle_id in searched or needle_name in searched:
                count += 1
    return count


def _cell(company_id: str, doc_type: str, fiscal_year: str) -> str:
    docs = list_documents(company_id=company_id, doc_type=doc_type)
    if any(d["fiscal_year"] == fiscal_year for d in docs):
        return "✅"
    outcome = _latest_attempt_outcome(company_id, doc_type, fiscal_year)
    return f"❌ {outcome}" if outcome else "❌ not attempted"


def generate_coverage(
    companies_file: CompaniesFile | None = None, out_path: Path = COVERAGE_MD
) -> str:
    """Builds docs/coverage.md: one row per company showing annual-report status
    per fiscal year plus shareholding/RPT/order counts, and totals across all
    fetch_attempts outcomes. This is the table Phase 1's exit criteria #2 and #4
    (spot-check notes) are recorded against."""
    cf = companies_file or _load_companies_file()

    header = (
        ["company_id", "name"]
        + [f"{fy} AR" for fy in cf.fiscal_years]
        + ["shareholding filings", "RPT disclosures", "orders"]
    )
    lines = [
        "# Document coverage",
        "",
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]

    outcome_totals: dict[str, int] = {}
    conn = connect()
    try:
        for outcome, count in conn.execute(
            "SELECT outcome, COUNT(*) FROM fetch_attempts GROUP BY outcome"
        ).fetchall():
            outcome_totals[outcome] = count
    finally:
        conn.close()

    for company in cf.companies:
        ar_cells = [_cell(company.company_id, "annual_report", fy) for fy in cf.fiscal_years]
        shareholding_n = len(list_documents(company_id=company.company_id, doc_type="shareholding"))
        rpt_n = len(list_documents(company_id=company.company_id, doc_type="rpt_disclosure"))
        orders_n = _order_count_for(company.company_id, company.name)
        row = (
            [company.company_id, company.name]
            + ar_cells
            + [str(shareholding_n), str(rpt_n), str(orders_n)]
        )
        lines.append("| " + " | ".join(row) + " |")

    all_docs = list_documents()
    lines += [
        "",
        "## Totals",
        "",
        f"- Registered documents: {len(all_docs)}",
        "- Fetch attempts by outcome: "
        + (", ".join(f"{k}={v}" for k, v in sorted(outcome_totals.items())) or "none yet"),
        "",
        "## Spot-check notes",
        "",
        "_Open 10 random registered files and confirm the company name and fiscal year on "
        "page 1; record findings here (Phase 1 exit criterion #4)._",
    ]

    text = "\n".join(lines) + "\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text)
    return text
