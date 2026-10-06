import re
from datetime import date
from typing import Any

ROLE_WORDS = frozenset(
    ["chairman", "chairperson", "secretary", "director", "manager", "ceo", "cfo", "officer"]
)


def validate_record(rec: Any) -> tuple[str, str]:
    """
    Run all business logic validation rules against a record.
    Returns (status, reason), where status can be 'accepted', 'review', or 'rejected'.
    Modifies the record in-place to fix non-fatal issues (like clearing invalid DINs).
    """
    status = "accepted"
    reason = ""

    # 1. Required fields
    if not hasattr(rec, "evidence") or not rec.evidence:
        return "rejected", "missing_evidence"

    names_to_check = []
    if hasattr(rec, "person_name"):
        names_to_check.append(rec.person_name)
    if hasattr(rec, "company_name"):
        names_to_check.append(rec.company_name)
    if hasattr(rec, "holder_name"):
        names_to_check.append(rec.holder_name)
    if hasattr(rec, "counterparty_name"):
        names_to_check.append(rec.counterparty_name)
    if hasattr(rec, "parent_company"):
        names_to_check.append(rec.parent_company)
    if hasattr(rec, "subsidiary_name"):
        names_to_check.append(rec.subsidiary_name)

    if not all(n and str(n).strip() for n in names_to_check):
        return "rejected", "empty_name"

    # 2. DIN Format
    if hasattr(rec, "din") and rec.din is not None and not re.match(r"^\d{8}$", str(rec.din)):
        rec.din = None  # Clear invalid DIN

    # 3. CIN format (robustness for future company ref schemas)
    if (
        hasattr(rec, "cin")
        and rec.cin is not None
        and not re.match(r"^[A-Za-z0-9]{21}$", str(rec.cin))
    ):
        rec.cin = None

    # 4. Name is not role
    if hasattr(rec, "person_name") and rec.person_name:
        words = re.findall(r"[a-z]+", rec.person_name.lower())
        # A short "name" containing a role word ("Company Secretary") is a title.
        if len(words) <= 3 and any(w in ROLE_WORDS for w in words):
            return "rejected", "name_is_role"

    # 5. pct_range
    pct_val = None
    if hasattr(rec, "pct_holding"):
        pct_val = rec.pct_holding
    if hasattr(rec, "pct_held"):
        pct_val = rec.pct_held

    if pct_val is not None and not (0 <= pct_val <= 100):
        return "rejected", "pct_out_of_range"

    # 6. pledge_le_holding (pledged as % of holding should be <= 100)
    if (
        hasattr(rec, "pct_pledged_of_holding")
        and rec.pct_pledged_of_holding is not None
        and not (0 <= rec.pct_pledged_of_holding <= 100)
    ):
        status = "review"
        reason = "pledge_out_of_range"

    # 7. date_order
    if (
        hasattr(rec, "appointed_on")
        and hasattr(rec, "ceased_on")
        and rec.appointed_on
        and rec.ceased_on
        and rec.appointed_on > rec.ceased_on
    ):
        status = "review"
        reason = "date_order_invalid"

    # 8. date_plausible
    dates = []
    if hasattr(rec, "appointed_on") and rec.appointed_on:
        dates.append(rec.appointed_on)
    if hasattr(rec, "ceased_on") and rec.ceased_on:
        dates.append(rec.ceased_on)
    if hasattr(rec, "as_of") and rec.as_of:
        dates.append(rec.as_of)
    if hasattr(rec, "order_date") and rec.order_date:
        dates.append(rec.order_date)

    if dates and hasattr(rec, "fiscal_year"):
        m = re.search(r"20\d{2}", rec.fiscal_year)
        if m:
            fy_start = int(m.group(0))
            for d in dates:
                if isinstance(d, date) and not (fy_start - 2 <= d.year <= fy_start + 2):
                    status = "review"
                    reason = "date_implausible"
                    break

    # 9. amount_nonneg
    if hasattr(rec, "amount_inr") and rec.amount_inr is not None and rec.amount_inr < 0:
        return "rejected", "amount_negative"

    # 10. amount_outlier
    # Placeholder heuristic: > 100,000 Crore INR is extremely rare for a single RPT in India
    if (
        hasattr(rec, "amount_inr")
        and rec.amount_inr is not None
        and rec.amount_inr > 1e12
        and status != "rejected"
    ):
        status = "review"
        reason = "amount_outlier"

    return status, reason
