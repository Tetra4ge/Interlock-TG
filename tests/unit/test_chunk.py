from server.parse.chunk import MAX_TOKENS, MIN_TABLE_TOKENS, build_chunks
from server.parse.tokens import estimate_tokens

DOC = "d" * 64


def _table(page_no: int, rows: list[list[str]]) -> dict:
    return {
        "page_no": page_no,
        "cells": [
            {"row": r, "col": c, "text": t}
            for r, cols in enumerate(rows)
            for c, t in enumerate(cols)
        ],
    }


def test_page_without_blank_lines_is_split_under_the_limit() -> None:
    # One 3000-token "paragraph": every line break is single, as PyMuPDF emits.
    page_text = "\n".join(f"line {i} " + "word " * 20 for i in range(110))
    chunks = build_chunks(
        DOC, [{"page_no": 1, "cleaned_text": page_text}], [], [], "C1", "FY2023-24"
    )

    assert len(chunks) > 3
    assert all(c["token_count"] <= MAX_TOKENS for c in chunks)
    assert all(c["token_count"] == estimate_tokens(c["text"]) for c in chunks)
    joined = "\n".join(c["text"] for c in chunks)
    assert all(f"line {i} " in joined for i in range(110))  # nothing dropped


def test_single_line_longer_than_a_chunk_is_split_on_words() -> None:
    chunks = build_chunks(DOC, [{"page_no": 1, "cleaned_text": "word " * 5000}], [], [], None, None)
    assert len(chunks) > 1 and all(c["token_count"] <= MAX_TOKENS for c in chunks)


def test_chunks_stay_inside_sections_and_have_deterministic_ids() -> None:
    pages = [{"page_no": n, "cleaned_text": f"page {n} " + "text " * 300} for n in (1, 2, 3)]
    sections = [("governance", 2, 2)]
    first = build_chunks(DOC, pages, [], sections, "C1", "FY2023-24")
    again = build_chunks(DOC, pages, [], sections, "C1", "FY2023-24")

    assert [c["chunk_id"] for c in first] == [c["chunk_id"] for c in again]
    assert len({c["chunk_id"] for c in first}) == len(first)
    gov = [c for c in first if c["section"] == "governance"]
    assert gov and all(c["page_start"] == c["page_end"] == 2 for c in gov)
    assert gov[0]["chunk_id"] == f"{DOC[:12]}-governance-0001"


def test_empty_and_tiny_tables_are_not_chunked() -> None:
    tables = [_table(1, [["", ""]]), _table(1, [["Total", "12"]])]
    assert build_chunks(DOC, [], tables, [], None, None) == []
    assert estimate_tokens("Total | 12") < MIN_TABLE_TOKENS


def test_large_table_is_split_by_rows_and_repeats_its_header() -> None:
    header = ["Name of Director", "Category", "DIN"]
    rows = [header] + [
        [f"Director Number {i}", "Independent Director", f"{i:08d}"] for i in range(200)
    ]
    chunks = build_chunks(DOC, [], [_table(4, rows)], [("governance", 4, 4)], "C1", "FY2023-24")

    assert len(chunks) > 1
    assert all(c["token_count"] <= MAX_TOKENS for c in chunks)
    assert all(c["text"].startswith("Name of Director | Category | DIN") for c in chunks)
    assert [c["chunk_id"] for c in chunks][:2] == [
        f"{DOC[:12]}-governance-table-0001",
        f"{DOC[:12]}-governance-table-0002",
    ]
    assert sum(c["text"].count("Independent Director") for c in chunks) == 200
