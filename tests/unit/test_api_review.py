import json

from server.api.review import pending_reviews
from tests.conftest import MemoryDB


def _queue(
    db: MemoryDB, rid: str, created: str, decided: str | None = None, payload: str | None = None
) -> None:
    db.execute(
        "INSERT INTO documents (doc_id, company_id, doc_type, fiscal_year, file_path, fetched_at) "
        "VALUES (?, 'TATASTEEL', 'annual_report', 'FY2023-24', 'x.pdf', 'now')",
        [f"doc-{rid}"],
    )
    db.execute(
        "INSERT INTO records (record_id, run_id, doc_id, record_type, payload_json, status) "
        "VALUES (?, 'run', ?, 'directors', ?, 'review')",
        [rid, f"doc-{rid}", payload if payload is not None else json.dumps({"name": f"P {rid}"})],
    )
    db.execute(
        "INSERT INTO review_queue (record_id, reason, created_at, decided_at) "
        "VALUES (?, 'unit_unknown', ?, ?)",
        [rid, created, decided],
    )
    db.commit()


def test_pending_items_are_listed_oldest_first_with_their_context(memdb: MemoryDB) -> None:
    _queue(memdb, "r2", "2026-01-02")
    _queue(memdb, "r1", "2026-01-01")
    items = pending_reviews(memdb)
    assert [i.record_id for i in items] == ["r1", "r2"]
    first = items[0]
    assert (first.record_type, first.reason, first.company_id, first.fiscal_year) == (
        "directors", "unit_unknown", "TATASTEEL", "FY2023-24",
    )  # fmt: skip
    assert first.payload == {"name": "P r1"}


def test_decided_items_are_not_pending(memdb: MemoryDB) -> None:
    _queue(memdb, "r1", "2026-01-01", decided="2026-01-05")
    _queue(memdb, "r2", "2026-01-02")
    assert [i.record_id for i in pending_reviews(memdb)] == ["r2"]


def test_the_limit_applies(memdb: MemoryDB) -> None:
    for i in range(5):
        _queue(memdb, f"r{i}", f"2026-01-0{i + 1}")
    assert len(pending_reviews(memdb, limit=2)) == 2


def test_a_bad_payload_does_not_hide_the_item(memdb: MemoryDB) -> None:
    _queue(memdb, "r1", "2026-01-01", payload="{not json")
    _queue(memdb, "r2", "2026-01-02", payload="[1, 2]")
    items = pending_reviews(memdb)
    assert [i.payload for i in items] == [{}, {}]


def test_an_empty_queue_is_an_empty_list(memdb: MemoryDB) -> None:
    assert pending_reviews(memdb) == []
