import csv
from pathlib import Path

ORDERS_INDEX = Path("data/orders_index.csv")
ORDERS_INDEX_HEADER = ["order_date", "regulator", "slug", "names_searched", "source_url"]


def append_order_index(
    *, order_date: str, regulator: str, slug: str, names_searched: str, source_url: str
) -> None:
    """Regulatory orders are found by hand (Step 8): search the regulator's order
    database by company/director name, save the PDF into data/inbox/ as
    `ORDER__regulatory_order__<date>__<slug>.pdf` (picked up by ingest_inbox()),
    and record the search here so it's clear what was checked and why. There is
    no automated adapter for this -- director names aren't known until Phase 3,
    so this list is revisited with a second search pass after entity resolution.
    """
    is_new = not ORDERS_INDEX.exists()
    ORDERS_INDEX.parent.mkdir(parents=True, exist_ok=True)
    with ORDERS_INDEX.open("a", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(ORDERS_INDEX_HEADER)
        writer.writerow([order_date, regulator, slug, names_searched, source_url])
