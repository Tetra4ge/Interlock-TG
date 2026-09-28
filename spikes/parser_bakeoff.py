"""Phase 0 PDF parser bake-off.

Extracts the governance (board/committee composition) and related-party-
transactions pages named in spikes/pages.yaml with both PyMuPDF and
pdfplumber, and writes the raw output of each to spikes/bakeoff_output/ for
manual scoring against docs/decisions/0001-pdf-parser.md.

Usage: uv run python -m spikes.parser_bakeoff
"""

import sys
import time
from pathlib import Path

import yaml

try:
    import fitz  # PyMuPDF
    import pdfplumber
except ImportError as e:
    print(f"Required package missing: {e}. Ensure pymupdf and pdfplumber are installed.")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
PAGES_FILE = ROOT / "spikes" / "pages.yaml"
OUTPUT_DIR = ROOT / "spikes" / "bakeoff_output"


def pymupdf_extract(path: Path, page_num: int) -> tuple[str, list, float]:
    start = time.perf_counter()
    doc = fitz.open(path)
    page = doc[page_num - 1]
    text = page.get_text("text")
    tables = [t.extract() for t in page.find_tables()]
    doc.close()
    elapsed_ms = (time.perf_counter() - start) * 1000
    return text, tables, elapsed_ms


def pdfplumber_extract(path: Path, page_num: int) -> tuple[str, list, float]:
    start = time.perf_counter()
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[page_num - 1]
        text = page.extract_text() or ""
        tables = page.extract_tables()
    elapsed_ms = (time.perf_counter() - start) * 1000
    return text, tables, elapsed_ms


def format_tables(tables: list) -> str:
    if not tables:
        return "(no tables detected)\n"
    out = []
    for i, table in enumerate(tables):
        out.append(f"-- table {i} --")
        for row in table:
            out.append(" | ".join("" if c is None else str(c) for c in row))
    return "\n".join(out) + "\n"


def run_bakeoff() -> None:
    config = yaml.safe_load(PAGES_FILE.read_text())
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    timings: list[tuple[str, str, str, float]] = []

    for report in config["reports"]:
        name = report["name"]
        path = ROOT / report["file"]
        if not path.exists():
            print(f"SKIP {name}: {path} not found")
            continue

        for kind in ("governance", "rpt"):
            page_num = report[kind]
            slug = name.split(" ")[0].replace("(", "").replace(")", "")

            mu_text, mu_tables, mu_ms = pymupdf_extract(path, page_num)
            pl_text, pl_tables, pl_ms = pdfplumber_extract(path, page_num)

            (OUTPUT_DIR / f"{slug}_{kind}_p{page_num}_pymupdf.txt").write_text(
                f"=== TEXT ===\n{mu_text}\n=== TABLES ===\n{format_tables(mu_tables)}"
            )
            (OUTPUT_DIR / f"{slug}_{kind}_p{page_num}_pdfplumber.txt").write_text(
                f"=== TEXT ===\n{pl_text}\n=== TABLES ===\n{format_tables(pl_tables)}"
            )

            timings.append((name, kind, "pymupdf", mu_ms))
            timings.append((name, kind, "pdfplumber", pl_ms))
            print(
                f"{name} / {kind} (p{page_num}): "
                f"pymupdf {mu_ms:.1f}ms ({len(mu_tables)} tables), "
                f"pdfplumber {pl_ms:.1f}ms ({len(pl_tables)} tables)"
            )

    mu_avg = sum(t for _, _, p, t in timings if p == "pymupdf") / max(
        1, sum(1 for _, _, p, _ in timings if p == "pymupdf")
    )
    pl_avg = sum(t for _, _, p, t in timings if p == "pdfplumber") / max(
        1, sum(1 for _, _, p, _ in timings if p == "pdfplumber")
    )
    print(f"\nAverage per-page time: pymupdf {mu_avg:.1f}ms, pdfplumber {pl_avg:.1f}ms")
    print(f"Raw output written to {OUTPUT_DIR}")


if __name__ == "__main__":
    run_bakeoff()
