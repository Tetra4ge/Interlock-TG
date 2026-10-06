import re
from typing import Any

from rapidfuzz import fuzz

from server.extract.units import parse_printed_number
from server.parse.clean import normalize_for_match


def _format_number(value: float) -> str:
    """12.5 → "12.5", 10.0 → "10": the way the figure is printed, so a whole
    percentage is not searched for as "10.0"."""
    return f"{value:.10f}".rstrip("0").rstrip(".")


def _digits(text: str) -> str:
    return re.sub(r"[^0-9]", "", text)


def grounded(quote: str, page_text: str, min_partial: int = 95) -> bool:
    """Check if a quote appears in the page text using rapidfuzz partial ratio."""
    q, p = normalize_for_match(quote), normalize_for_match(page_text)
    if len(q) < 8:
        return False
    if q in p:
        return True
    # tolerate tiny extraction differences (e.g. a dropped space in a table)
    return fuzz.partial_ratio(q, p) >= min_partial


def get_page_text(parsed: dict, page_no: int) -> str:
    """Safely fetch the cleaned text of a specific page from the parsed document."""
    for page in parsed.get("pages", []):
        if page["page_no"] == page_no:
            return page.get("cleaned_text", page.get("text", ""))
    return ""


def check_grounding(rec: Any, parsed: dict) -> tuple[str, str]:
    """
    Checks if a record's evidence is physically grounded in the source text.
    Returns (status, reason).
    Modifies rec.evidence.page in-place if an off-by-one page error is fixed.
    """
    if not hasattr(rec, "evidence") or not rec.evidence:
        return "rejected", "missing_evidence"

    evidence = rec.evidence
    quote = evidence.quote
    page_no = evidence.page

    # 1. Check if the quote exists on the stated page
    page_text = get_page_text(parsed, page_no)
    is_grounded = grounded(quote, page_text)

    if not is_grounded:
        # Check neighboring pages (fixing common LLM off-by-one errors)
        prev_text = get_page_text(parsed, page_no - 1)
        if grounded(quote, prev_text):
            evidence.page = page_no - 1
            is_grounded = True
        else:
            next_text = get_page_text(parsed, page_no + 1)
            if grounded(quote, next_text):
                evidence.page = page_no + 1
                is_grounded = True

    if not is_grounded:
        return "rejected", "ungrounded_quote"

    norm_quote = normalize_for_match(quote)

    # 2. Numeric records check (stop the LLM from inventing numbers not in the quote).
    #    Optional numbers that were not extracted (None) have nothing to check.
    numeric_value: str | None = None
    if hasattr(rec, "amount_inr"):
        printed = parse_printed_number(str(getattr(rec, "amount_raw", "") or ""))
        numeric_value = _format_number(printed) if printed is not None else None
    elif getattr(rec, "pct_holding", None) is not None:
        numeric_value = _format_number(rec.pct_holding)
    elif getattr(rec, "pct_held", None) is not None:
        numeric_value = _format_number(rec.pct_held)

    if numeric_value and _digits(numeric_value) not in _digits(norm_quote):
        return "rejected", "ungrounded_number"

    # 3. Person records check (ensure surname is actually in the quote)
    person_name = None
    if hasattr(rec, "person_name"):
        person_name = rec.person_name
    elif hasattr(rec, "holder_name") and getattr(rec, "holder_kind", "") == "person":
        person_name = rec.holder_name

    if person_name:
        parts = person_name.split()
        if parts:
            surname = normalize_for_match(parts[-1])
            if surname not in norm_quote:
                return "rejected", "ungrounded_surname"

    return "accepted", ""
