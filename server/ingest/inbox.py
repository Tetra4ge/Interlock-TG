import re
from pathlib import Path

from server.ingest.registry import register

INBOX_DIR = Path("data/inbox")
PROCESSED_DIR = INBOX_DIR / "processed"

# <company_id>__<doc_type>__<fiscal_year>[__<period>].pdf
# ORDER__regulatory_order__<order-date-YYYY-MM-DD>__<slug>.pdf
# Double underscores avoid clashing with hyphens in fiscal years or company ids
# like BAJAJ-AUTO.
NAME_RE = re.compile(
    r"^(?P<company>[A-Z0-9-]+)__(?P<doctype>[a-z_]+)__(?P<fy>FY\d{4}-\d{2}|\d{4}-\d{2}-\d{2})"
    r"(?:__(?P<period>[A-Za-z0-9-]+))?\.pdf$"
)


def parse_name(name: str) -> dict[str, str | None] | None:
    m = NAME_RE.match(name)
    return m.groupdict() if m else None


def ingest_inbox(inbox: Path = INBOX_DIR, processed: Path = PROCESSED_DIR) -> dict:
    """Registers every well-named PDF in `inbox`, moving each into `processed/`
    once registered. Badly-named files (including real non-PDF content saved
    with a .pdf name) are reported and left in place so they can be fixed and
    rerun."""
    processed.mkdir(parents=True, exist_ok=True)
    registered = 0
    duplicates = 0
    bad_names: list[str] = []

    for f in sorted(inbox.glob("*.pdf")):
        meta = parse_name(f.name)
        if meta is None:
            bad_names.append(f.name)
            continue

        company_id = None if meta["company"] == "ORDER" else meta["company"]
        fiscal_year = meta["fy"] if meta["fy"] and meta["fy"].startswith("FY") else None

        try:
            _doc_id, created = register(
                f.read_bytes(),
                company_id=company_id,
                doc_type=meta["doctype"] or "",
                fiscal_year=fiscal_year,
                source_url=None,
            )
        except ValueError:
            bad_names.append(f.name)
            continue

        if created:
            registered += 1
        else:
            duplicates += 1
        f.rename(processed / f.name)

    return {"registered": registered, "duplicates": duplicates, "bad_names": bad_names}
