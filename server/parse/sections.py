import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from server.store.db import connect
from server.parse.clean import normalize_for_match

logger = logging.getLogger(__name__)

KEYWORDS = {
    "governance": ["report on corporate governance", "corporate governance report"],
    "board_report": ["directors' report", "board's report"],
    "auditor": ["independent auditor's report", "auditors' report"],
    "related_party": ["related party disclosures", "related party transactions"],
    "subsidiaries": ["subsidiaries, associates and joint ventures", "statement containing salient features of the financial statement of subsidiaries"],
    "shareholding": ["shareholding pattern", "distribution of shareholding", "shareholding of promoters"]
}

MAX_LENGTHS = {
    "governance": 40,
    "board_report": 50,
    "auditor": 20,
    "related_party": 20,
    "subsidiaries": 15,
    "shareholding": 10
}

def detect_sections_for_doc(doc_id: str, parsed_file: Path) -> None:
    """Scan a parsed document's cleaned text and detect page ranges for target sections."""
    if not parsed_file.exists():
        return
        
    data = json.loads(parsed_file.read_text())
    pages = data.get("pages", [])
    if not pages:
        return
        
    detected: Dict[str, Dict[str, Optional[int]]] = {}
    
    # TOC heuristic (first 15 pages) looking for keyword + page number
    page_offset = None
    for i, page in enumerate(pages[:15]):
        norm_text = normalize_for_match(page.get("text", ""))
        lines = norm_text.splitlines()
        for line in lines:
            for kind, kws in KEYWORDS.items():
                if kind in detected:
                    continue
                for kw in kws:
                    if kw in line:
                        # try to find a number at the end of the line
                        match = re.search(r'\b(\d+)\s*$', line)
                        if match:
                            printed_page = int(match.group(1))
                            # if we don't have an offset yet, establish it
                            if page_offset is None:
                                # assume the target printed page is later in the PDF
                                # e.g. printed page 1 might be PDF page 10. Offset = 9
                                # So PDF page = printed_page + offset
                                # We can't know offset for sure until we verify. But as a naive first step:
                                pass
                            
                            # For safety in this pilot, TOC parsing is fragile. We will rely primarily 
                            # on heading scans which are much more robust, as requested by the fallback.
    
    # Heading scan fallback (which is often primary for robustness)
    for page in pages:
        page_no = page["page_no"]
        # Use cleaned text for better matching
        norm_text = normalize_for_match(page.get("cleaned_text", ""))
        lines = norm_text.splitlines()[:8]  # first ~8 lines
        
        for kind, kws in KEYWORDS.items():
            if kind in detected:
                continue # Already found start
                
            for kw in kws:
                if any(kw in line for line in lines):
                    # Check for standalone vs consolidated for related_party
                    subkind = kind
                    if kind == "related_party":
                        if "consolidated" in norm_text:
                            subkind = "related_party_consolidated"
                        else:
                            subkind = "related_party_standalone"
                            
                    if subkind not in detected:
                        detected[subkind] = {"start": page_no, "end": None}
                    break
                    
    # Section end = the page before the next detected section start, capped at max length
    starts: List[Tuple[str, int]] = sorted(
        [(kind, info["start"]) for kind, info in detected.items() if info["start"] is not None],
        key=lambda x: x[1]
    )
    
    last_page = pages[-1]["page_no"]
    
    for i, (kind, start_page) in enumerate(starts):
        base_kind = kind.replace("_standalone", "").replace("_consolidated", "")
        max_len = MAX_LENGTHS.get(base_kind, 40)
        end_page = start_page + max_len
        
        if i + 1 < len(starts):
            next_start = starts[i+1][1]
            if next_start > start_page:
                end_page = min(end_page, next_start - 1)
                
        end_page = min(end_page, last_page)
        detected[kind]["end"] = end_page
        
    # Store in DB
    conn = connect()
    for kind, info in detected.items():
        conn.execute(
            "INSERT OR REPLACE INTO sections (doc_id, kind, page_start, page_end) VALUES (?, ?, ?, ?)",
            [doc_id, kind, info["start"], info["end"]]
        )
    conn.commit()
    conn.close()

def detect_all_sections() -> None:
    """Run section detection for all parsed documents."""
    conn = connect()
    rows = conn.execute("SELECT doc_id FROM documents WHERE status = 'parsed'").fetchall()
    conn.close()
    
    if not rows:
        print("No 'parsed' documents found for section detection.")
        return
        
    print(f"Detecting sections for {len(rows)} parsed documents...")
    out_dir = Path("data/parsed")
    
    for (doc_id,) in rows:
        parsed_file = out_dir / f"{doc_id}.json"
        try:
            detect_sections_for_doc(doc_id, parsed_file)
            print(f"Successfully detected sections for {doc_id}.")
        except Exception as e:
            logger.exception(f"Failed section detection for {doc_id}")
            print(f"Failed section detection for {doc_id}: {e}")
            
    print("Section detection complete.")
