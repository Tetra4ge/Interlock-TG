# ADR 0001: PDF Parser Selection

## Context
During Phase 0, we ran a bake-off spike (`spikes/parser_bakeoff.py`) to evaluate PyMuPDF (`fitz`) vs `pdfplumber` for extracting text and tables from our target Annual Reports.

## Decision
We will use a **hybrid approach**:
1. **PyMuPDF (`fitz`)** for all standard raw text extraction. It is significantly faster and handles general reading order well.
2. **`pdfplumber`** strictly for extracting complex tabular data (like Board Composition or Related-Party Transactions). PyMuPDF struggles with complex column alignments, whereas `pdfplumber` explicitly models grid structures.

## Consequences
- The pipeline (`Phase 2: Parse`) will conditionally route pages to `pdfplumber` only if table extraction is required, to save processing time.
