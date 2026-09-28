from pathlib import Path

import pytest

from server.ingest import inbox


@pytest.mark.parametrize(
    "name,expected",
    [
        (
            "BAJFINANCE__annual_report__FY2023-24.pdf",
            {
                "company": "BAJFINANCE",
                "doctype": "annual_report",
                "fy": "FY2023-24",
                "period": None,
            },
        ),
        (
            "BAJAJ-AUTO__annual_report__FY2022-23.pdf",
            {
                "company": "BAJAJ-AUTO",
                "doctype": "annual_report",
                "fy": "FY2022-23",
                "period": None,
            },
        ),
        (
            "TATASTEEL__shareholding__FY2023-24__Q4.pdf",
            {"company": "TATASTEEL", "doctype": "shareholding", "fy": "FY2023-24", "period": "Q4"},
        ),
        (
            "ORDER__regulatory_order__2024-03-15__insider-trading.pdf",
            {
                "company": "ORDER",
                "doctype": "regulatory_order",
                "fy": "2024-03-15",
                "period": "insider-trading",
            },
        ),
    ],
)
def test_parse_name_valid(name: str, expected: dict) -> None:
    assert inbox.parse_name(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "not_a_pdf_name.pdf",
        "BAJFINANCE_annual_report_FY2023-24.pdf",  # single underscores
        "bajfinance__annual_report__FY2023-24.pdf",  # lowercase company
        "BAJFINANCE__annual_report__2023-24.pdf",  # missing FY prefix
        "BAJFINANCE__annual_report__FY2023-24.docx",  # wrong extension
    ],
)
def test_parse_name_invalid(name: str) -> None:
    assert inbox.parse_name(name) is None


def test_ingest_inbox_moves_registered_files_and_reports_bad_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inbox_dir = tmp_path / "inbox"
    processed_dir = inbox_dir / "processed"
    inbox_dir.mkdir()

    good = inbox_dir / "BAJFINANCE__annual_report__FY2023-24.pdf"
    good.write_bytes(b"%PDF-1.4\nfake\n")
    bad = inbox_dir / "not_a_pdf_name.pdf"
    bad.write_bytes(b"%PDF-1.4\nfake\n")

    registered_calls: list[dict] = []

    def fake_register(content: bytes, **kwargs: object) -> tuple[str, bool]:
        registered_calls.append(kwargs)
        return "deadbeef", True

    monkeypatch.setattr(inbox, "register", fake_register)

    report = inbox.ingest_inbox(inbox=inbox_dir, processed=processed_dir)

    assert report["registered"] == 1
    assert report["duplicates"] == 0
    assert report["bad_names"] == ["not_a_pdf_name.pdf"]
    assert not good.exists()
    assert (processed_dir / good.name).exists()
    assert bad.exists()  # left in place for the user to fix
    assert registered_calls == [
        {
            "company_id": "BAJFINANCE",
            "doc_type": "annual_report",
            "fiscal_year": "FY2023-24",
            "source_url": None,
        }
    ]


def test_ingest_inbox_rejects_non_pdf_content_as_bad_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inbox_dir = tmp_path / "inbox"
    processed_dir = inbox_dir / "processed"
    inbox_dir.mkdir()

    fake_pdf = inbox_dir / "BAJFINANCE__annual_report__FY2023-24.pdf"
    fake_pdf.write_bytes(b"<html>error page</html>")

    def raising_register(content: bytes, **kwargs: object) -> tuple[str, bool]:
        raise ValueError("not a PDF (missing %PDF header)")

    monkeypatch.setattr(inbox, "register", raising_register)

    report = inbox.ingest_inbox(inbox=inbox_dir, processed=processed_dir)

    assert report["registered"] == 0
    assert report["bad_names"] == [fake_pdf.name]
    assert fake_pdf.exists()
