from datetime import date
from typing import Any

from server.extract.schemas import Evidence, ShareholdingRecord


def parse_number(val: str) -> float | None:
    if not val:
        return None
    val = val.replace(",", "").strip()
    if val.lower() in ("nil", "-", "na", "n/a"):
        return 0.0
    try:
        return float(val)
    except ValueError:
        return None


def parse_shareholding_table(
    doc_id: str,
    company_name: str,
    table_page: int,
    table_cells: list[dict[str, Any]],
    as_of_date: date,
) -> list[ShareholdingRecord] | None:
    """
    Attempt to extract shareholding records from a table using heuristic rules.
    Returns None if rules fail (fallback to LLM).
    """
    # Reconstruct rows
    rows_map: dict[int, dict[int, str]] = {}
    for cell in table_cells:
        r = cell["row"]
        if r not in rows_map:
            rows_map[r] = {}
        rows_map[r][cell["col"]] = cell["text"]

    if not rows_map:
        return None

    sorted_rows = sorted(rows_map.keys())

    # 1. Find header row and map columns
    header_row_idx = None
    col_mapping = {}

    for r in sorted_rows[:5]:  # search first 5 rows
        row_text = " ".join([rows_map[r][c].lower() for c in sorted(rows_map[r].keys())])
        if "name" in row_text and "%" in row_text:
            header_row_idx = r
            for c in sorted(rows_map[r].keys()):
                h_text = rows_map[r][c].lower()
                if "name" in h_text or "shareholder" in h_text:
                    col_mapping["name"] = c
                elif (
                    "%" in h_text
                    and ("total" in h_text or "shares" in h_text)
                    and "pledge" not in h_text
                ):
                    col_mapping["pct_holding"] = c
                elif "%" in h_text and ("pledge" in h_text or "encumber" in h_text):
                    col_mapping["pct_pledged"] = c
            break

    if "name" not in col_mapping or "pct_holding" not in col_mapping:
        return None  # Header mapping failed

    records = []
    fail_count = 0
    total_rows = 0

    # 2. Extract rows
    for r in sorted_rows:
        if header_row_idx is not None and r <= header_row_idx:
            continue

        name = rows_map[r].get(col_mapping["name"], "").strip()
        if not name or name.lower() in ("total", "sub-total"):
            continue

        total_rows += 1
        pct_holding_str = rows_map[r].get(col_mapping["pct_holding"], "")
        pct_holding = parse_number(pct_holding_str)

        pct_pledged = None
        if "pct_pledged" in col_mapping:
            pct_pledged = parse_number(rows_map[r].get(col_mapping["pct_pledged"], ""))

        if pct_holding is None:
            fail_count += 1
            continue

        row_str = " | ".join([rows_map[r][c] for c in sorted(rows_map[r].keys())])

        records.append(
            ShareholdingRecord(
                holder_name=name,
                holder_kind="category" if "promoter" in name.lower() else "person",
                company_name=company_name,
                pct_holding=pct_holding,
                pct_pledged_of_holding=pct_pledged,
                is_promoter_group=True,
                as_of=as_of_date,
                evidence=Evidence(doc_id=doc_id, page=table_page, quote=row_str[:600]),
            )
        )

    # 3. Fallback check (>20% failure)
    if total_rows == 0 or (fail_count / total_rows) > 0.2:
        return None

    return records
