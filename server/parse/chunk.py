import json
import logging
from pathlib import Path
from typing import Any

from server.common.config import pipeline_section
from server.parse.tokens import estimate_tokens
from server.store.db import connect

logger = logging.getLogger(__name__)

_CFG = pipeline_section("chunk")
MAX_TOKENS = int(_CFG.get("max_tokens", 800))
OVERLAP_TOKENS = int(_CFG.get("overlap_tokens", 60))
# pdfplumber reports many one- or two-cell "tables" (page furniture, stray
# rules). Their text is already in the page text, so they only add noise.
MIN_TABLE_TOKENS = 20


def _split_oversized(text: str, max_tokens: int) -> list[str]:
    """Split one over-long paragraph on line breaks, then on words, so that
    no piece exceeds max_tokens. PDF pages often have no blank lines at all,
    which makes a whole page a single "paragraph"."""
    if estimate_tokens(text) <= max_tokens:
        return [text]
    max_chars = max_tokens * 4  # inverse of estimate_tokens
    pieces: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > max_chars:  # a single line longer than a chunk
            cut = line.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if current:
                pieces.append(current)
                current = ""
            pieces.append(line[:cut])
            line = line[cut:].lstrip()
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > max_chars and current:
            pieces.append(current)
            current = line
        else:
            current = candidate
    if current:
        pieces.append(current)
    return [p for p in pieces if p.strip()]


def _table_row_groups(rows: list[str], max_tokens: int) -> list[str]:
    """Render table rows into one or more texts of at most max_tokens, each
    repeating the header row so a later group still names its columns."""
    if not rows:
        return []
    header, body = rows[0], rows[1:]
    groups: list[str] = []
    current = [header]
    for row in body:
        if estimate_tokens("\n".join([*current, row])) > max_tokens and len(current) > 1:
            groups.append("\n".join(current))
            current = [header]
        current.append(row)
    groups.append("\n".join(current))
    return [g for piece in groups for g in _split_oversized(piece, max_tokens)]


def build_chunks(
    doc_id: str,
    pages: list[dict[str, Any]],
    tables: list[dict[str, Any]],
    sections_rows: list[tuple[str, int, int]],
    company_id: str | None,
    fiscal_year: str | None,
) -> list[dict]:
    """Token-limited chunks that never cross a section boundary. Text chunks
    overlap by up to OVERLAP_TOKENS; each table is chunked on its own."""

    def make(chunk_id: str, sec: str, start: int, end: int, text: str) -> dict:
        return {
            "chunk_id": chunk_id,
            "doc_id": doc_id,
            "company_id": company_id,
            "fiscal_year": fiscal_year,
            "section": sec,
            "page_start": start,
            "page_end": end,
            "text": text,
            "token_count": estimate_tokens(text),
        }

    def section_of(page_no: int) -> str:
        return next(
            (kind for kind, start, end in sections_rows if start <= page_no <= end), "other"
        )

    # Paragraph pieces per section, each tagged with the page it came from.
    section_pieces: dict[str, list[tuple[int, str]]] = {}
    for page in pages:
        sec = section_of(page["page_no"])
        text = page.get("cleaned_text", page.get("text", ""))
        for para in text.split("\n\n"):
            para = para.strip()
            if not para:
                continue
            for piece in _split_oversized(para, MAX_TOKENS - OVERLAP_TOKENS):
                section_pieces.setdefault(sec, []).append((page["page_no"], piece))

    chunks: list[dict] = []
    for sec, pieces in section_pieces.items():
        counter = 1
        current: list[tuple[int, str]] = []
        current_tokens = 0
        for page_no, piece in pieces:
            piece_tokens = estimate_tokens(piece)
            if current and current_tokens + piece_tokens > MAX_TOKENS:
                text = "\n\n".join(t for _, t in current)
                chunks.append(
                    make(
                        f"{doc_id[:12]}-{sec}-{counter:04d}",
                        sec,
                        current[0][0],
                        current[-1][0],
                        text,
                    )
                )
                counter += 1

                # Carry the tail of the closed chunk forward as overlap.
                overlap: list[tuple[int, str]] = []
                overlap_tokens = 0
                for prev in reversed(current):
                    t = estimate_tokens(prev[1])
                    if overlap_tokens + t > OVERLAP_TOKENS:
                        break
                    overlap.insert(0, prev)
                    overlap_tokens += t
                current, current_tokens = overlap, overlap_tokens
            current.append((page_no, piece))
            current_tokens += piece_tokens
        if current:
            text = "\n\n".join(t for _, t in current)
            chunks.append(
                make(f"{doc_id[:12]}-{sec}-{counter:04d}", sec, current[0][0], current[-1][0], text)
            )

    table_counters: dict[str, int] = {}
    for table in tables:
        page_no = table["page_no"]
        sec = section_of(page_no)

        rows_map: dict[int, list[tuple[int, str]]] = {}
        for cell in table["cells"]:
            rows_map.setdefault(cell["row"], []).append((cell["col"], cell["text"]))
        rows = [
            " | ".join(c[1] for c in sorted(rows_map[r], key=lambda x: x[0]))
            for r in sorted(rows_map)
        ]
        rows = [r for r in rows if r.replace("|", "").strip()]
        if estimate_tokens("\n".join(rows)) < MIN_TABLE_TOKENS:
            continue

        caption = f"{table['caption']}\n\n" if table.get("caption") else ""
        for group in _table_row_groups(rows, MAX_TOKENS):
            n = table_counters.get(sec, 0) + 1
            table_counters[sec] = n
            chunks.append(
                make(f"{doc_id[:12]}-{sec}-table-{n:04d}", sec, page_no, page_no, caption + group)
            )

    return chunks


def chunk_document(doc_id: str, parsed_file: Path) -> list[dict]:
    """Break a parsed PDF into token-limited chunks, respecting section boundaries."""
    if not parsed_file.exists():
        return []

    data = json.loads(parsed_file.read_text())

    conn = connect()
    doc_row = conn.execute(
        "SELECT company_id, fiscal_year FROM documents WHERE doc_id = ?", [doc_id]
    ).fetchone()
    company_id, fiscal_year = doc_row if doc_row else (None, None)

    sections_rows = conn.execute(
        "SELECT kind, page_start, page_end FROM sections WHERE doc_id = ? ORDER BY page_start",
        [doc_id],
    ).fetchall()
    conn.close()

    return build_chunks(
        doc_id,
        data.get("pages", []),
        data.get("tables", []),
        [tuple(r) for r in sections_rows],
        company_id,
        fiscal_year,
    )


def chunk_all() -> None:
    """Run chunking for all parsed documents and save to data/chunks."""
    conn = connect()
    # Every document that has been parsed, including ones already extracted
    # or flagged, so that `build-graph --from chunk` can re-chunk the corpus.
    rows = conn.execute(
        "SELECT doc_id FROM documents WHERE status IN ('parsed', 'extracted', 'flagged')"
    ).fetchall()
    conn.close()

    if not rows:
        print("No parsed documents found to chunk.")
        return

    in_dir = Path("data/parsed")
    out_dir = Path("data/chunks")
    out_dir.mkdir(parents=True, exist_ok=True)

    total_chunks = 0
    for (doc_id,) in rows:
        parsed_file = in_dir / f"{doc_id}.json"
        if not parsed_file.exists():
            # Never overwrite existing chunks with an empty list just because
            # the (gitignored) parsed JSON is not on this machine.
            print(f"Skipping {doc_id}: no parsed file at {parsed_file}.")
            continue
        try:
            doc_chunks = chunk_document(doc_id, parsed_file)
            chunk_file = out_dir / f"{doc_id}_chunks.json"
            chunk_file.write_text(json.dumps(doc_chunks, indent=2, ensure_ascii=False))
            print(f"Document {doc_id} yielded {len(doc_chunks)} chunks.")
            total_chunks += len(doc_chunks)
        except Exception as e:
            logger.exception(f"Failed to chunk {doc_id}")
            print(f"Failed to chunk {doc_id}: {e}")

    print(f"Chunking complete. Created {total_chunks} total chunks.")
