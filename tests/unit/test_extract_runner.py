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
