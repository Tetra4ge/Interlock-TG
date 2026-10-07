import json
from collections import defaultdict
from typing import Any

import numpy as np
import yaml
from pydantic import BaseModel

from server.pipelines.common.scope import COMPANIES_PATH, company_display_names
from server.resolve.normalize import norm_company
from server.store.db import connect

TOP_PEOPLE = 10
RUPEES_PER_CRORE = 1e7

# Mentions per entity in the resolver's merge_log. Every accepted record that
# became a fact edge contributes one mention per endpoint, so this is the fact-edge
# degree used to spot hub nodes (the MENTIONS edges to chunks are deliberately not
# counted: expansion never walks them).


def entity_degrees() -> dict[str, int]:
    db = connect()
    try:
        rows = db.execute("SELECT entity_id, COUNT(*) FROM merge_log GROUP BY entity_id").fetchall()
    finally:
        db.close()
    return {r[0]: int(r[1]) for r in rows}


def hub_ids(percentile: float, min_degree: int) -> set[str]:
    """Entities whose fact-edge degree is above both the given percentile and an
    absolute floor. The floor stops tiny graphs flagging their busiest entity."""
    degrees = entity_degrees()
    if not degrees:
        return set()
    threshold = max(float(np.percentile(list(degrees.values()), percentile)), float(min_degree))
    return {eid for eid, d in degrees.items() if d > threshold}


class StatItem(BaseModel):
    topic: str  # the relation type the statistic is about, or "COVERAGE"
    text: str


def _company(company_id: str) -> str:
    return company_display_names().get(company_id, company_id)


def _accepted_records(db: Any) -> list[tuple[str, str, dict, str, str]]:
    rows = db.execute(
        """
        SELECT r.record_id, r.record_type, r.payload_json, d.company_id, d.fiscal_year
        FROM records r JOIN documents d ON r.doc_id = d.doc_id
        WHERE r.status IN ('accepted', 'fixed')
        """
    ).fetchall()
    return [(r[0], r[1], json.loads(r[2]), r[3] or "", r[4] or "") for r in rows]


def _board_stats(records: list[tuple[str, str, dict, str, str]]) -> list[StatItem]:
    boards: dict[tuple[str, str], dict[str, bool]] = defaultdict(dict)
    for _, rtype, payload, company, fy in records:
        if rtype == "directors" and company:
            name = str(payload.get("name") or payload.get("person_name") or "").strip()
            if name:
                boards[(company, fy)][name] = bool(payload.get("is_independent"))
    return [
        StatItem(
            topic="DIRECTOR_OF",
            text=f"{_company(company)} had {_plural(len(people), 'director')} on record in {fy}, "
            f"of whom {sum(people.values())} are independent.",
        )
        for (company, fy), people in sorted(boards.items())
    ]


def _auditor_stats(records: list[tuple[str, str, dict, str, str]]) -> list[StatItem]:
    firms: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for _, rtype, payload, company, fy in records:
        name = str(payload.get("firm_name") or "").strip()
        if rtype == "auditor" and company and name:
            firms[company][str(payload.get("fiscal_year") or fy)].add(name)

    items: list[StatItem] = []
    for company, by_year in sorted(firms.items()):
        years = sorted(by_year)
        for fy in years:
            items.append(
                StatItem(
                    topic="AUDITED_BY",
                    text=f"{_company(company)}'s statutory auditor in {fy}: "
                    + "; ".join(sorted(by_year[fy]))
                    + ".",
                )
            )
        for prev, cur in zip(years, years[1:], strict=False):
            same = {norm_company(f) for f in by_year[prev]} == {
                norm_company(f) for f in by_year[cur]
            }
            items.append(
                StatItem(
                    topic="AUDITED_BY",
                    text=f"{_company(company)} "
                    + ("kept the same" if same else "changed its")
                    + f" statutory auditor between {prev} and {cur}.",
                )
            )
    return items


def _rpt_stats(records: list[tuple[str, str, dict, str, str]]) -> list[StatItem]:
    totals: dict[tuple[str, str], list[float]] = defaultdict(list)
    for _, rtype, payload, company, fy in records:
        if rtype == "rpt" and company:
            totals[(company, str(payload.get("fiscal_year") or fy))].append(
                float(payload.get("amount_inr") or 0.0)
            )
    return [
        StatItem(
            topic="PARTY_TO",
            text=f"{_company(company)} reported {len(amounts)} related-party transactions in {fy} "
            f"totalling \u20b9 {sum(amounts) / RUPEES_PER_CRORE:,.2f} crore.",
        )
        for (company, fy), amounts in sorted(totals.items())
    ]


def _subsidiary_stats(records: list[tuple[str, str, dict, str, str]]) -> list[StatItem]:
    subs: dict[tuple[str, str], set[str]] = defaultdict(set)
    for _, rtype, payload, company, fy in records:
        name = str(payload.get("subsidiary_name") or "").strip()
        if rtype == "subsidiaries" and company and name:
            subs[(company, fy)].add(name)
    return [
        StatItem(
            topic="SUBSIDIARY_OF",
            text=(
                f"{_company(company)} listed "
                f"{_plural(len(names), 'subsidiary', 'subsidiaries')} in {fy}."
            ),
        )
        for (company, fy), names in sorted(subs.items())
    ]


def _board_seat_stats(db: Any) -> list[StatItem]:
    rows = db.execute(
        """
        SELECT m.entity_id, e.canonical_name, d.company_id
        FROM merge_log m
        JOIN records r ON r.record_id = substr(m.mention_id, 1, instr(m.mention_id, ':') - 1)
        JOIN documents d ON d.doc_id = r.doc_id
        JOIN entities e ON e.entity_id = m.entity_id
        WHERE m.mention_id LIKE '%:person' AND r.status IN ('accepted', 'fixed')
          AND r.record_type = 'directors' AND d.company_id IS NOT NULL
        """
    ).fetchall()
    boards: dict[str, tuple[str, set[str]]] = {}
    for entity_id, name, company in rows:
        boards.setdefault(entity_id, (name, set()))[1].add(company)

    multi = sorted(
        ((n, cs) for n, cs in boards.values() if len(cs) > 1),
        key=lambda x: (-len(x[1]), x[0]),
    )[:TOP_PEOPLE]
    if not multi:
        return [
            StatItem(
                topic="DIRECTOR_OF",
                text="No person appears on more than one company's board in the extracted records.",
            )
        ]
    return [
        StatItem(
            topic="DIRECTOR_OF",
            text=f"{name} sits on {len(cs)} boards in the dataset: "
            + ", ".join(sorted(_company(c) for c in cs))
            + ".",
        )
        for name, cs in multi
    ]


def _plural(n: int, noun: str, plural: str | None = None) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {plural or noun + 's'}"


def _sector_stats(with_data: set[str]) -> list[StatItem]:
    data = yaml.safe_load(COMPANIES_PATH.read_text()) or {}
    by_sector: dict[str, list[dict]] = defaultdict(list)
    for c in data.get("companies", []):
        if c.get("sector"):
            by_sector[c["sector"]].append(c)

    items = []
    for sector, companies in sorted(by_sector.items()):
        extracted = sorted(c["name"] for c in companies if c["company_id"] in with_data)
        listed = ", ".join(sorted(c["name"] for c in companies))
        items.append(
            StatItem(
                topic="IN_SECTOR",
                text=f"Sector {sector}: {_plural(len(companies), 'company')} tracked ({listed}); "
                f"{len(extracted)} with extracted records"
                + (f" ({', '.join(extracted)})." if extracted else "."),
            )
        )
    return items


def dataset_stats_pack() -> list[StatItem]:
    """Corpus-wide statistics for questions about the whole dataset ("which
    sector...", "how many..."), computed from the accepted records that built
    the graph so the figures match what the graph contains. Provenance is the
    build itself, not a page: each item says so."""
    db = connect()
    try:
        records = _accepted_records(db)
        if not records:
            return []
        docs = db.execute("SELECT COUNT(DISTINCT doc_id) FROM documents").fetchone()[0]
        run = db.execute(
            "SELECT run_id FROM extraction_runs ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        seats = _board_seat_stats(db)
    finally:
        db.close()

    companies = sorted({c for _, _, _, c, _ in records if c})
    years = sorted({fy for _, _, _, _, fy in records if fy})
    basis = (
        f" [computed from {len(records)} accepted records in the graph build"
        f"{f', extraction run {run[0]}' if run else ''}]"
    )
    coverage = StatItem(
        topic="COVERAGE",
        text=f"The dataset has {docs} documents covering {len(companies)} companies "
        f"({', '.join(_company(c) for c in companies)}) and fiscal years {', '.join(years)}. "
        "Figures below only reflect these companies.",
    )
    pack = [
        coverage,
        *_board_stats(records),
        *seats,
        *_auditor_stats(records),
        *_rpt_stats(records),
        *_subsidiary_stats(records),
        *_sector_stats(set(companies)),
    ]
    return [i.model_copy(update={"text": i.text + basis}) for i in pack]
