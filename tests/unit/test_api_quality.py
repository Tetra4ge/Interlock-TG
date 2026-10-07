import json

import pytest

from server.api.quality import data_quality, provenance_complete_pct
from tests.conftest import MemoryDB


def _doc(db: MemoryDB, doc_id: str, company: str, status: str = "extracted") -> None:
    db.execute(
        "INSERT INTO documents (doc_id, company_id, doc_type, fiscal_year, file_path, "
        "fetched_at, status) VALUES (?, ?, 'annual_report', 'FY2023-24', 'x.pdf', 'now', ?)",
        [doc_id, company, status],
    )


def _rec(db: MemoryDB, rid: str, doc: str, payload: dict, status: str = "accepted") -> None:
    db.execute(
        "INSERT INTO records (record_id, run_id, doc_id, record_type, payload_json, status) "
        "VALUES (?, 'run', ?, 'directors', ?, ?)",
        [rid, doc, json.dumps(payload), status],
    )


GOOD = {"evidence": {"doc_id": "d", "page": 4, "quote": "Sanjiv Bajaj"}}
NO_QUOTE = {"evidence": {"doc_id": "d", "page": 4, "quote": ""}}
LEGACY = {"name": "x", "page": 9}  # a page, but no evidence block


@pytest.fixture
def db(memdb: MemoryDB) -> MemoryDB:
    _doc(memdb, "d1", "TATASTEEL")
    _doc(memdb, "d2", "TATAMOTORS", status="failed")
    _doc(memdb, "d3", "BAJFINANCE", status="parsed")
    _rec(memdb, "r1", "d1", GOOD)
    _rec(memdb, "r2", "d1", NO_QUOTE)
    _rec(memdb, "r3", "d3", LEGACY)
    _rec(memdb, "r4", "d3", GOOD)
    _rec(memdb, "r5", "d2", GOOD, status="rejected")
    for eid, kind in (("C:1", "company"), ("P:1", "person"), ("P:2", "person")):
        memdb.execute(
            "INSERT INTO entities (entity_id, kind, canonical_name, aliases_text) "
            "VALUES (?, ?, 'n', '')",
            [eid, kind],
        )
    for mention, eid, method in (("a:person", "P:1", "exact_name"), ("b:person", "P:2", "fuzzy")):
        memdb.execute(
            "INSERT INTO merge_log (mention_id, entity_id, method) VALUES (?, ?, ?)",
            [mention, eid, method],
        )
    memdb.execute(
        "INSERT INTO review_queue (record_id, reason, created_at) VALUES ('r2','x','now')"
    )
    memdb.commit()
    return memdb


def test_counts_come_straight_from_the_store(db: MemoryDB) -> None:
    q = data_quality(db)
    assert (q.documents, q.documents_parsed, q.documents_failed) == (3, 2, 1)
    assert (q.records_total, q.records_accepted, q.records_rejected) == (5, 4, 1)
    assert q.companies == 2  # only companies with accepted records
    assert q.review_queue == 1
    assert q.entities_by_kind == {"company": 1, "person": 2}
    assert q.mentions_by_method == {"exact_name": 1, "fuzzy": 1}


def test_provenance_is_measured_not_assumed(db: MemoryDB) -> None:
    # of 4 accepted records only r1 and r4 carry a quoted evidence page
    assert provenance_complete_pct(db) == 50.0
    assert data_quality(db).provenance_complete_pct == 50.0


def test_an_empty_store_reports_zeros_and_no_provenance(memdb: MemoryDB) -> None:
    q = data_quality(memdb)
    assert q.documents == 0 and q.records_total == 0 and q.provenance_complete_pct is None
    assert q.entities_by_kind == {}


def test_a_broken_store_degrades_to_zeros() -> None:
    class Broken:
        def execute(self, *a: object) -> None:
            raise RuntimeError("no such table")

    q = data_quality(Broken())
    assert q.documents == 0 and q.provenance_complete_pct is None
