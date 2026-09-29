import json
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Any

from server.store.db import connect
from server.parse.tokens import estimate_tokens

logger = logging.getLogger(__name__)

MAX_TOKENS = 800
OVERLAP_TOKENS = 60

def chunk_document(doc_id: str, parsed_file: Path) -> List[dict]:
    """Break a parsed PDF into token-limited chunks, respecting section boundaries."""
    if not parsed_file.exists():
        return []
        
    data = json.loads(parsed_file.read_text())
    pages = data.get("pages", [])
    tables = data.get("tables", [])
    
    conn = connect()
    doc_row = conn.execute("SELECT company_id, fiscal_year FROM documents WHERE doc_id = ?", [doc_id]).fetchone()
    company_id, fiscal_year = doc_row if doc_row else (None, None)
    
    sections_rows = conn.execute(
        "SELECT kind, page_start, page_end FROM sections WHERE doc_id = ? ORDER BY page_start", 
        [doc_id]
    ).fetchall()
    conn.close()
    
    # Map each page to a section
    page_to_section = {}
    for page in pages:
        p_no = page["page_no"]
        sec_kind = "other"
        for s_kind, start, end in sections_rows:
            if start <= p_no <= end:
                sec_kind = s_kind
                break
        page_to_section[p_no] = sec_kind
        
    chunks = []
    chunk_counters: Dict[str, int] = {}
    
    # Group text pages by section
    section_texts: Dict[str, List[dict]] = {}
    for page in pages:
        sec = page_to_section[page["page_no"]]
        if sec not in section_texts:
            section_texts[sec] = []
        section_texts[sec].append({
            "page_no": page["page_no"],
            "text": page.get("cleaned_text", page.get("text", ""))
        })
        
    # Process text chunks per section
    for sec, sec_pages in section_texts.items():
        if sec not in chunk_counters:
            chunk_counters[sec] = 1
            
        current_chunk_paragraphs: List[str] = []
        current_tokens = 0
        start_page = sec_pages[0]["page_no"]
        last_page = start_page
        
        for p in sec_pages:
            page_no = p["page_no"]
            paragraphs = p["text"].split("\n\n")
            
            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue
                    
                para_tokens = estimate_tokens(para)
                
                if current_tokens + para_tokens > MAX_TOKENS and current_chunk_paragraphs:
                    # Close the current chunk
                    text = "\n\n".join(current_chunk_paragraphs)
                    chunks.append({
                        "chunk_id": f"{doc_id[:12]}-{sec}-{chunk_counters[sec]:04d}",
                        "doc_id": doc_id,
                        "company_id": company_id,
                        "fiscal_year": fiscal_year,
                        "section": sec,
                        "page_start": start_page,
                        "page_end": last_page,
                        "text": text,
                        "token_count": current_tokens
                    })
                    chunk_counters[sec] += 1
                    
                    # Compute overlap from the end of current_chunk_paragraphs
                    overlap_paras: List[str] = []
                    overlap_toks = 0
                    for op in reversed(current_chunk_paragraphs):
                        t = estimate_tokens(op)
                        if overlap_toks + t > OVERLAP_TOKENS:
                            break
                        overlap_paras.insert(0, op)
                        overlap_toks += t
                        
                    current_chunk_paragraphs = overlap_paras
                    current_chunk_paragraphs.append(para)
                    current_tokens = overlap_toks + para_tokens
                    start_page = page_no
                    last_page = page_no
                else:
                    current_chunk_paragraphs.append(para)
                    current_tokens += para_tokens
                    last_page = page_no
                    
        # Flush any remaining text in this section
        if current_chunk_paragraphs:
            text = "\n\n".join(current_chunk_paragraphs)
            chunks.append({
                "chunk_id": f"{doc_id[:12]}-{sec}-{chunk_counters[sec]:04d}",
                "doc_id": doc_id,
                "company_id": company_id,
                "fiscal_year": fiscal_year,
                "section": sec,
                "page_start": start_page,
                "page_end": last_page,
                "text": text,
                "token_count": current_tokens
            })
            chunk_counters[sec] += 1
            
    # Process tables as isolated chunks
    for table in tables:
        page_no = table["page_no"]
        sec = page_to_section.get(page_no, "other")
        if sec not in chunk_counters:
            chunk_counters[sec] = 1
            
        # Reconstruct table text visually (simplified Markdown-like format)
        table_text = ""
        # Handle optional caption
        if "caption" in table and table["caption"]:
            table_text += f"{table['caption']}\n\n"
            
        # Group cells by row
        rows_map: Dict[int, List[Tuple[int, str]]] = {}
        for cell in table["cells"]:
            r = cell["row"]
            if r not in rows_map:
                rows_map[r] = []
            rows_map[r].append((cell["col"], cell["text"]))
            
        for r in sorted(rows_map.keys()):
            row_cells = [c[1] for c in sorted(rows_map[r], key=lambda x: x[0])]
            table_text += " | ".join(row_cells) + "\n"
            
        token_count = estimate_tokens(table_text)
        
        chunks.append({
            "chunk_id": f"{doc_id[:12]}-{sec}-table-{chunk_counters[sec]:04d}",
            "doc_id": doc_id,
            "company_id": company_id,
            "fiscal_year": fiscal_year,
            "section": sec,
            "page_start": page_no,
            "page_end": page_no,
            "text": table_text.strip(),
            "token_count": token_count
        })
        chunk_counters[sec] += 1
        
    return chunks

def chunk_all() -> None:
    """Run chunking for all parsed documents and save to data/chunks."""
    conn = connect()
    rows = conn.execute("SELECT doc_id FROM documents WHERE status = 'parsed'").fetchall()
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
