import hashlib
from datetime import UTC, datetime
from pathlib import Path

from server.store.db import connect

RAW_DIR = Path("data/raw")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def register(
    content: bytes,
    *,
    company_id: str | None,
    doc_type: str,
    fiscal_year: str | None,
    source_url: str | None,
) -> tuple[str, bool]:
    """Store `content` under its content hash and insert a `documents` row.

    Returns (doc_id, created). created=False if a document with these exact
    bytes was already registered (identical hash -> identical id -> no-op),
    including when the same PDF is filed under a different company/target
    (e.g. a combined filing) -- the second call is a no-op here, logged as a
    duplicate by the caller; multi-company attribution is handled later by
    extraction, not by storing the file twice.
    """
    if not content.startswith(b"%PDF"):
        raise ValueError("not a PDF (missing %PDF header)")

    doc_id = sha256_bytes(content)
    path = RAW_DIR / f"{doc_id}.pdf"

    conn = connect()
    try:
        row = conn.execute("SELECT 1 FROM documents WHERE doc_id=?", [doc_id]).fetchone()
        if row:
            return doc_id, False

        RAW_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(content)
        tmp.replace(path)

        conn.execute(
            """
            INSERT INTO documents
            (doc_id, company_id, doc_type, fiscal_year, source_url,
             file_path, fetched_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'registered')
            """,
            [
                doc_id,
                company_id,
                doc_type,
                fiscal_year,
                source_url,
                str(path),
                datetime.now(UTC).isoformat(),
            ],
        )
        conn.commit()
        return doc_id, True
    finally:
        conn.close()


def already_have(company_id: str | None, doc_type: str, fiscal_year: str | None) -> bool:
    """True if a registered document already exists for this (company, doc_type,
    fiscal_year). Doesn't distinguish period_label -- callers fetching multi-file
    types (e.g. several shareholding filings per year) should check period-level
    state themselves before calling `register`."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM documents WHERE company_id IS ? AND doc_type=? AND fiscal_year IS ?",
            [company_id, doc_type, fiscal_year],
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def list_documents(
    *, company_id: str | None = None, doc_type: str | None = None
) -> list[dict]:
    """Registered documents, optionally filtered. Used by the coverage report."""
    conn = connect()
    try:
        sql = "SELECT doc_id, company_id, doc_type, fiscal_year, source_url, status FROM documents"
        clauses = []
        params: list[str] = []
        if company_id is not None:
            clauses.append("company_id = ?")
            params.append(company_id)
        if doc_type is not None:
            clauses.append("doc_type = ?")
            params.append(doc_type)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        rows = conn.execute(sql, params).fetchall()
        cols = ["doc_id", "company_id", "doc_type", "fiscal_year", "source_url", "status"]
        return [dict(zip(cols, r, strict=True)) for r in rows]
    finally:
        conn.close()


def record_attempt(
    *,
    company_id: str | None,
    doc_type: str,
    fiscal_year: str | None,
    url: str | None,
    http_status: int | None,
    outcome: str,
    error: str | None,
) -> None:
    """Logs one fetch attempt (ok/duplicate/manual_needed/resolve_failed/failed)."""
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO fetch_attempts
            (company_id, doc_type, fiscal_year, url, attempted_at, http_status, outcome, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                company_id,
                doc_type,
                fiscal_year,
                url,
                datetime.now(UTC).isoformat(),
                http_status,
                outcome,
                error,
            ],
        )
        conn.commit()
    finally:
        conn.close()
