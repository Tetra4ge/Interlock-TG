from datetime import date

import pytest

from server.extract import runner
from server.extract.schemas import Evidence, RegulatoryActionRecord

ORDER_TEXT = "SEBI imposed a penalty of Rs. 5 lakh on Example Industries Limited."


def _add_doc(db, doc_id: str, doc_type: str, status: str, company: str | None = None) -> None:
    db.execute(
        "INSERT INTO documents (doc_id, company_id, doc_type, fiscal_year, file_path, "
        "fetched_at, status) VALUES (?, ?, ?, ?, 'x.pdf', 'now', ?)",
        [doc_id, company, doc_type, "FY2023-24" if company else None, status],
    )


@pytest.fixture
def wired(memdb, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(runner, "connect", lambda: memdb)
    monkeypatch.setattr(
        runner,
        "load_parsed",
        lambda _doc_id: {
            "pages": [
                {"page_no": 1, "cleaned_text": ORDER_TEXT},
                {"page_no": 2, "cleaned_text": ""},
            ],
            "tables": [],
        },
    )
    return memdb


def test_regulatory_order_is_extracted_as_one_whole_document_section(
    wired, monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_doc(wired, "order1", "regulatory_order", "flagged")
    seen: list[tuple[str, list[int]]] = []

    def fake_llm(task: str, doc_row: dict, window: list[dict]) -> list:
        seen.append((task, [p["page_no"] for p in window]))
        return [
            RegulatoryActionRecord(
                order_id="WTM/1",
                regulator="SEBI",
                order_date=date(2023, 6, 1),
                action_type="penalty",
                named_entities=["Example Industries Limited"],
                summary="Penalty imposed.",
                evidence=Evidence(doc_id="order1", page=1, quote=ORDER_TEXT),
            )
        ]

    monkeypatch.setattr(runner, "llm_extract", fake_llm)
    runner.extract_all("run1")

    assert seen == [("regulatory", [1, 2])]
    rows = wired.execute("SELECT record_type, status FROM records").fetchall()
    assert rows == [("regulatory", "accepted")]
    status = wired.execute("SELECT status FROM documents WHERE doc_id='order1'").fetchone()[0]
    assert status == "extracted"


def test_annual_report_without_sections_is_still_flagged(
    wired, monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_doc(wired, "ar1", "annual_report", "parsed", company="C1")
    monkeypatch.setattr(runner, "llm_extract", lambda *_a: pytest.fail("must not be called"))
    runner.extract_all("run1")
    status = wired.execute("SELECT status FROM documents WHERE doc_id='ar1'").fetchone()[0]
    assert status == "flagged"


def test_fiscal_year_end() -> None:
    assert runner.fiscal_year_end("FY2023-24") == date(2024, 3, 31)
    assert runner.fiscal_year_end(None) is None
    assert runner.fiscal_year_end("2023-24") is None


def test_rule_parsed_shareholding_is_dated_at_fiscal_year_end(
    memdb, monkeypatch: pytest.MonkeyPatch
) -> None:
    header = ["Name of shareholder", "% of total shares", "% of shares pledged"]
    row = ["Tata Sons Private Limited", "43.71%", "Nil"]
    cells = [
        {"row": r, "col": c, "text": text}
        for r, cols in enumerate([header, row])
        for c, text in enumerate(cols)
    ]
    monkeypatch.setattr(runner, "connect", lambda: memdb)
    monkeypatch.setattr(
        runner,
        "load_parsed",
        lambda _d: {
            "pages": [{"page_no": 7, "cleaned_text": " | ".join(row)}],
            "tables": [{"page_no": 7, "table_idx": 0, "cells": cells}],
        },
    )
    monkeypatch.setattr(runner, "llm_extract", lambda *_a: pytest.fail("rules should handle it"))
    _add_doc(memdb, "ar2", "annual_report", "parsed", company="TATAMOTORS")
    memdb.execute("INSERT INTO sections VALUES ('ar2', 'shareholding', 7, 7)")

    runner.extract_all("run1")

    payload, status = memdb.execute("SELECT payload_json, status FROM records").fetchone()
    assert status == "accepted"
    assert '"as_of":"2024-03-31"' in payload
    assert '"pct_holding":43.71' in payload


def test_llm_request_allows_long_json_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_call(req):
        captured["req"] = req
        return type("R", (), {"error": None, "content": '{"records": []}'})()

    monkeypatch.setattr(runner, "call_llm", fake_call)
    runner.llm_extract("directors", {"doc_id": "d", "company_id": "C1"}, [{"page_no": 1}])
    assert captured["req"].max_tokens == runner.EXTRACT_MAX_TOKENS >= 4000


def test_extraction_run_records_the_real_commit(wired, monkeypatch: pytest.MonkeyPatch) -> None:
    _add_doc(wired, "order2", "regulatory_order", "parsed")
    monkeypatch.setattr(runner, "llm_extract", lambda *_a: [])
    monkeypatch.setattr(runner, "git_state", lambda: {"git_commit": "abc123", "git_dirty": False})
    runner.extract_all("run9")
    assert wired.execute("SELECT git_commit FROM extraction_runs").fetchone()[0] == "abc123"
