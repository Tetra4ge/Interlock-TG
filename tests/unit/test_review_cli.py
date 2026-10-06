import json

import pytest

from server.extract import review


def _seed(db, record_id: str) -> None:
    db.execute(
        "INSERT INTO records (record_id, run_id, doc_id, record_type, payload_json, status, reason)"
        " VALUES (?, 'run', 'doc', 'directors', ?, 'review', 'ungrounded_quote')",
        [record_id, json.dumps({"person_name": "A", "evidence": {"page": 3, "quote": "q"}})],
    )
    db.execute(
        "INSERT INTO review_queue (record_id, reason, created_at) VALUES (?, 'r', ?)",
        [record_id, f"2026-01-0{record_id[-1]}"],
    )


def test_decisions_are_saved(memdb, monkeypatch: pytest.MonkeyPatch) -> None:
    for rid in ("r1", "r2", "r3"):
        _seed(memdb, rid)
    fixed = json.dumps({"person_name": "B"})
    answers = iter(["a", "r", "e", fixed])
    monkeypatch.setattr(review, "connect", lambda: memdb)
    monkeypatch.setattr("builtins.input", lambda *_a: next(answers))

    review.review_cli()

    rows = memdb.execute(
        "SELECT r.record_id, r.status, q.decision, q.decided_at IS NOT NULL, "
        "q.decided_payload_json, r.payload_json "
        "FROM records r JOIN review_queue q USING (record_id) ORDER BY r.record_id"
    ).fetchall()
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [
        ("r1", "accepted", "accepted", 1),
        ("r2", "rejected", "rejected", 1),
        ("r3", "fixed", "fixed", 1),
    ]
    assert rows[2][4] == fixed and rows[2][5] == fixed
