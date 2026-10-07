import json

import pytest

from server.resolve import mentions as mentions_mod


def _seed_auditor_record(db) -> None:
    db.execute(
        "INSERT INTO documents "
        "(doc_id, company_id, doc_type, fiscal_year, file_path, fetched_at, status) "
        "VALUES "
        "('doc1', 'TATAMOTORS', 'annual_report', 'FY2023-24', 'x.pdf', '2026-01-01', 'extracted')"
    )
    payload = {
        "firm_name": "B S R & Co. LLP",
        "firm_registration_no": "101248W/W-100022",
        "fiscal_year": "FY2023-24",
        "evidence": {"doc_id": "doc1", "page": 1, "quote": "B S R & Co. LLP"},
    }
    db.execute(
        "INSERT INTO records (record_id, run_id, doc_id, record_type, payload_json, status) "
        "VALUES ('rec1', 'run1', 'doc1', 'auditor', ?, 'accepted')",
        (json.dumps(payload),),
    )
    db.commit()


def test_auditor_record_produces_a_context_company_mention(memdb, monkeypatch: pytest.MonkeyPatch):
    """Regression: build_mentions must emit a `{record_id}:context_company` mention for
    auditor records, the same as it does for directors/rpt/subsidiaries records. Without it,
    the graph loader can never resolve the reporting-company side of an AUDITED_BY edge, and
    every auditor fact is silently dropped from the graph (no error, zero edges)."""
    _seed_auditor_record(memdb)
    monkeypatch.setattr(mentions_mod, "connect", lambda: memdb)

    found = mentions_mod.build_mentions()
    by_id = {m.mention_id: m for m in found}

    assert "rec1:context_company" in by_id, (
        "auditor records must produce a context_company mention so the reporting company "
        "side of AUDITED_BY can be resolved"
    )
    assert by_id["rec1:context_company"].kind == "company"
    assert "rec1:audit_firm" in by_id
    assert by_id["rec1:audit_firm"].kind == "audit_firm"
    assert by_id["rec1:audit_firm"].ids == {"frn": "101248W/W-100022"}
