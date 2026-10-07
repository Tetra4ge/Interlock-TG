"""Read-only access to the source documents behind citations: the text of a parsed
page, and the stored PDF so the browser can open it at that page."""

import json
import re
from pathlib import Path
from typing import Any

from server.api.schemas import DocumentPage
from server.settings import ROOT

DOC_ID_RE = re.compile(r"[A-Za-z0-9]{8,64}")  # sha256 hex in practice
PARSED_DIR = ROOT / "data/parsed"
RAW_DIR = ROOT / "data/raw"


class DocumentNotFound(LookupError):
    pass


def valid_doc_id(doc_id: str) -> bool:
    return bool(DOC_ID_RE.fullmatch(doc_id))


def pdf_path(doc_id: str, raw_dir: Path | None = None) -> Path | None:
    """The stored PDF, or None. The id is validated so it cannot name a path."""
    if not valid_doc_id(doc_id):
        return None
    path = (raw_dir or RAW_DIR) / f"{doc_id}.pdf"
    return path if path.is_file() else None


def page_text(
    conn: Any,
    doc_id: str,
    page: int,
    parsed_dir: Path | None = None,
    raw_dir: Path | None = None,
) -> DocumentPage:
    if not valid_doc_id(doc_id):
        raise ValueError("invalid document id")
    if page < 1:
        raise ValueError("page must be 1 or more")

    parsed = (parsed_dir or PARSED_DIR) / f"{doc_id}.json"
    if not parsed.is_file():
        raise DocumentNotFound(f"no parsed text for document {doc_id[:12]}...")
    pages = json.loads(parsed.read_text()).get("pages", [])
    match = next((p for p in pages if p.get("page_no") == page), None)
    if match is None:
        raise DocumentNotFound(f"page {page} not found in document {doc_id[:12]}...")

    meta = conn.execute(
        "SELECT company_id, fiscal_year, doc_type FROM documents WHERE doc_id = ?", [doc_id]
    ).fetchone()
    return DocumentPage(
        doc_id=doc_id,
        page=page,
        text=match.get("cleaned_text", match.get("text", "")),
        company_id=meta[0] if meta else None,
        fiscal_year=meta[1] if meta else None,
        doc_type=meta[2] if meta else None,
        pdf_available=pdf_path(doc_id, raw_dir) is not None,
    )
