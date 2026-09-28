from pathlib import Path

import pytest

from server.ingest import registry


class FakeCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple]:
        return self._rows

    def fetchone(self) -> tuple | None:
        return self._rows[0] if self._rows else None


class FakeConn:
    """In-memory stand-in for the `documents`/`fetch_attempts` tables, just
    enough to exercise registry.py without touching a real DB file."""

    def __init__(self) -> None:
        self.documents: list[tuple] = []  # (doc_id,)
        self.inserts: list[tuple] = []

    def execute(self, sql: str, params: list | None = None) -> FakeCursor:
        params = params or []
        sql_upper = sql.strip().upper()
        if sql_upper.startswith("SELECT 1 FROM DOCUMENTS"):
            doc_id = params[0]
            return FakeCursor([(1,)] if (doc_id,) in self.documents else [])
        if sql_upper.startswith("INSERT INTO DOCUMENTS"):
            self.documents.append((params[0],))
            self.inserts.append((sql, params))
            return FakeCursor([])
        self.inserts.append((sql, params))
        return FakeCursor([])

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeConn:
    conn = FakeConn()
    monkeypatch.setattr(registry, "connect", lambda: conn)
    monkeypatch.setattr(registry, "RAW_DIR", tmp_path)
    return conn


PDF_BYTES = b"%PDF-1.4\n%fake pdf content for tests\n"


def test_register_same_bytes_twice_creates_once() -> None:
    doc_id_1, created_1 = registry.register(
        PDF_BYTES,
        company_id="C1",
        doc_type="annual_report",
        fiscal_year="FY2023-24",
        source_url="https://example.com/a.pdf",
    )
    doc_id_2, created_2 = registry.register(
        PDF_BYTES,
        company_id="C1",
        doc_type="annual_report",
        fiscal_year="FY2023-24",
        source_url="https://example.com/a.pdf",
    )

    assert doc_id_1 == doc_id_2
    assert created_1 is True
    assert created_2 is False


def test_register_writes_content_addressed_file(tmp_path: Path) -> None:
    doc_id, _created = registry.register(
        PDF_BYTES,
        company_id="C1",
        doc_type="annual_report",
        fiscal_year="FY2023-24",
        source_url=None,
    )

    assert doc_id == registry.sha256_bytes(PDF_BYTES)
    assert (tmp_path / f"{doc_id}.pdf").read_bytes() == PDF_BYTES


def test_register_rejects_non_pdf_bytes() -> None:
    with pytest.raises(ValueError, match="not a PDF"):
        registry.register(
            b"<html>not a pdf</html>",
            company_id="C1",
            doc_type="annual_report",
            fiscal_year="FY2023-24",
            source_url=None,
        )
