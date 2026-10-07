import json
from pathlib import Path

import pytest

from server.api.documents import DocumentNotFound, page_text, pdf_path, valid_doc_id
from tests.conftest import MemoryDB

DOC = "a" * 64


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    parsed, raw = tmp_path / "parsed", tmp_path / "raw"
    parsed.mkdir()
    raw.mkdir()
    (parsed / f"{DOC}.json").write_text(
        json.dumps(
            {
                "pages": [
                    {"page_no": 1, "text": "raw one"},
                    {"page_no": 2, "text": "raw", "cleaned_text": "clean two"},
                ]
            }
        )
    )
    return parsed, raw


@pytest.mark.parametrize("good", [DOC, "abcdef12", "A1b2C3d4"])
def test_document_ids_are_alphanumeric(good: str) -> None:
    assert valid_doc_id(good)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "short",
        "../etc/passwd",
        "a/b" * 5,
        DOC + "x" * 10,
        "ab cd ef gh",
        f"{DOC}.pdf",
        "a" * 8 + "\n",
    ],
)
def test_path_like_ids_are_rejected(bad: str) -> None:
    assert not valid_doc_id(bad)
    assert pdf_path(bad) is None


def test_page_text_prefers_cleaned_text_and_adds_metadata(
    memdb: MemoryDB, dirs: tuple[Path, Path]
) -> None:
    memdb.execute(
        "INSERT INTO documents (doc_id, company_id, doc_type, fiscal_year, file_path, fetched_at) "
        "VALUES (?, 'TATASTEEL', 'annual_report', 'FY2023-24', 'x', 'now')",
        [DOC],
    )
    (dirs[1] / f"{DOC}.pdf").write_bytes(b"%PDF-1.4")
    two = page_text(memdb, DOC, 2, *dirs)
    assert (two.text, two.company_id, two.fiscal_year, two.pdf_available) == (
        "clean two",
        "TATASTEEL",
        "FY2023-24",
        True,
    )
    assert page_text(memdb, DOC, 1, *dirs).text == "raw one"


def test_a_document_missing_from_the_store_still_returns_its_text(
    memdb: MemoryDB, dirs: tuple[Path, Path]
) -> None:
    out = page_text(memdb, DOC, 1, *dirs)
    assert out.company_id is None and out.pdf_available is False


def test_missing_document_page_or_file_is_not_found(
    memdb: MemoryDB, dirs: tuple[Path, Path]
) -> None:
    with pytest.raises(DocumentNotFound, match="page 9"):
        page_text(memdb, DOC, 9, *dirs)
    with pytest.raises(DocumentNotFound, match="no parsed text"):
        page_text(memdb, "b" * 64, 1, *dirs)


def test_invalid_input_is_a_value_error(memdb: MemoryDB, dirs: tuple[Path, Path]) -> None:
    with pytest.raises(ValueError, match="document id"):
        page_text(memdb, "../x", 1, *dirs)
    with pytest.raises(ValueError, match="page"):
        page_text(memdb, DOC, 0, *dirs)


def test_pdf_path_only_returns_existing_files(dirs: tuple[Path, Path]) -> None:
    assert pdf_path(DOC, dirs[1]) is None
    (dirs[1] / f"{DOC}.pdf").write_bytes(b"%PDF")
    assert pdf_path(DOC, dirs[1]) == dirs[1] / f"{DOC}.pdf"
