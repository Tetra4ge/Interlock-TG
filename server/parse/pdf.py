import json
import logging
from pathlib import Path

import fitz
import pdfplumber

from server.store.db import connect
from server.parse.clean import find_furniture, clean_page_text

logger = logging.getLogger(__name__)

PARSER_VERSION = "p1"


def parse_document(doc_id: str, path: Path, out_dir: Path, min_chars: int) -> Path:
    out = out_dir / f"{doc_id}.json"
    if out.exists():
        data = json.loads(out.read_text())
        if data.get("parser_version") == PARSER_VERSION:
            return out  # idempotent skip
            
    pages_data, tables = [], []
    doc = fitz.open(path)
    
    # First pass: grab all text for furniture detection
    raw_texts = []
    for i, page in enumerate(doc, start=1):
        raw_texts.append(page.get_text("text"))
        
    furniture = find_furniture(raw_texts, ratio=0.6)
    
    # Second pass: construct page dicts with raw and cleaned text
    for i, text in enumerate(raw_texts, start=1):
        cleaned = clean_page_text(text, furniture)
        pages_data.append({
            "page_no": i, 
            "text": text,
            "cleaned_text": cleaned,
            "is_probable_scan": len(text.strip()) < min_chars
        })
                      
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            for t_idx, rows in enumerate(page.extract_tables() or []):
                cells = [{"row": r, "col": c, "text": (v or "").strip()}
                         for r, row in enumerate(rows) for c, v in enumerate(row)]
                tables.append({"page_no": i, "table_idx": t_idx, "cells": cells})
                
    out.write_text(json.dumps({"doc_id": doc_id, "parser_version": PARSER_VERSION,
                               "pages": pages_data, "tables": tables}, ensure_ascii=False))
    return out


def parse_all() -> None:
    out_dir = Path("data/parsed")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    conn = connect()
    rows = conn.execute("SELECT doc_id, file_path FROM documents WHERE status = 'registered'").fetchall()
    
    if not rows:
        print("No documents found with status 'registered' to parse.")
        conn.close()
        return

    print(f"Found {len(rows)} documents to parse.")
    
    for row in rows:
        doc_id, file_path = row
        print(f"Parsing document {doc_id} from {file_path}...")
        try:
            parse_document(doc_id, Path(file_path), out_dir, min_chars=50)
            conn.execute("UPDATE documents SET status = 'parsed', error = NULL WHERE doc_id = ?", [doc_id])
            conn.commit()
            print(f"Successfully parsed {doc_id}.")
        except Exception as e:
            logger.exception(f"Failed to parse {doc_id}")
            conn.execute("UPDATE documents SET status = 'failed', error = ? WHERE doc_id = ?", [str(e), doc_id])
            conn.commit()
            print(f"Failed to parse {doc_id}: {e}")
            
    conn.close()
