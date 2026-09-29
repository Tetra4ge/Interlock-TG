import json
import logging
import uuid
from pathlib import Path
from typing import List, Dict, Any, Tuple

from pydantic import BaseModel, ValidationError

from server.store.db import connect
from server.llm.models import LLMRequest, LLMMessage
from server.llm.gateway import call_llm
from server.settings import settings
from server.parse.tokens import estimate_tokens
from server.extract.rules.shareholding_table import parse_shareholding_table
from server.extract.schemas import (
    DirectorsOut,
    ShareholdingOut,
    RelatedPartyTxnsOut,
    AuditorsOut,
    SubsidiariesOut,
    RegulatoryActionsOut
)

logger = logging.getLogger(__name__)

SECTION_TO_TASK = {
    "governance": ["directors"],
    "board_report": ["directors"],
    "auditor": ["auditor"],
    "related_party_standalone": ["rpt"],
    "subsidiaries": ["subsidiaries"],
    "shareholding": ["shareholding"],
    "regulatory": ["regulatory"] 
}

TASK_SCHEMAS = {
    "directors": DirectorsOut,
    "shareholding": ShareholdingOut,
    "rpt": RelatedPartyTxnsOut,
    "auditor": AuditorsOut,
    "subsidiaries": SubsidiariesOut,
    "regulatory": RegulatoryActionsOut
}

def load_parsed(doc_id: str) -> dict:
    parsed_file = Path(f"data/parsed/{doc_id}.json")
    if not parsed_file.exists():
        return {}
    return json.loads(parsed_file.read_text())

def page_windows(pages: List[dict], max_tokens: int = 4000) -> List[List[dict]]:
    """Group pages into windows with 1 page overlap."""
    windows = []
    current_window = []
    current_tokens = 0
    
    for page in pages:
        text = page.get("cleaned_text", page.get("text", ""))
        tokens = estimate_tokens(text)
        
        if current_tokens + tokens > max_tokens and current_window:
            windows.append(current_window)
            # Start new window with 1 page overlap
            current_window = [current_window[-1], page]
            current_tokens = estimate_tokens(current_window[0].get("cleaned_text", "")) + tokens
        else:
            current_window.append(page)
            current_tokens += tokens
            
    if current_window:
        windows.append(current_window)
        
    return windows

def check(rec: Any, parsed: dict) -> Tuple[str, str]:
    # Stub for Step 10
    return "accepted", ""

def format_pages_block(pages: List[dict]) -> str:
    blocks = []
    for page in pages:
        blocks.append(f"[PAGE {page['page_no']}]\n{page.get('cleaned_text', page.get('text', ''))}")
    return "\n\n".join(blocks)

def llm_extract(task: str, doc_row: dict, window_pages: List[dict]) -> List[Any]:
    sys_prompt = Path("server/extract/prompts/system_v1.md").read_text()
    task_prompt_template = Path(f"server/extract/prompts/{task}_v1.md").read_text()
    
    pages_block = format_pages_block(window_pages)
    
    task_prompt = task_prompt_template.format(
        company_name=doc_row.get("company_id", "Unknown Company"), # ideally from entities table
        fiscal_year=doc_row.get("fiscal_year", "Unknown Year"),
        pages_block=pages_block
    )
    
    schema_model = TASK_SCHEMAS[task]
    
    # Use generic model from settings, or specifically hardcode a fallback
    model = "llama3-70b-8192" 
    
    req = LLMRequest(
        provider="groq",
        model=model,
        role="extractor",
        messages=[
            LLMMessage(role="system", content=sys_prompt),
            LLMMessage(role="user", content=task_prompt)
        ],
        response_schema=schema_model.model_json_schema(),
        temperature=0.0
    )
    
    resp = call_llm(req)
    if resp.error:
        logger.error(f"LLM call error: {resp.error}")
        return []
        
    try:
        parsed_out = schema_model.model_validate_json(resp.content)
        return getattr(parsed_out, "records", [])
    except ValidationError as e:
        # Retry once on JSON validation error
        logger.warning("LLM Extraction validation failed. Retrying once...")
        retry_prompt = f"{task_prompt}\n\nYour previous output failed validation: {e}\nReturn corrected JSON."
        req.messages[1].content = retry_prompt
        resp2 = call_llm(req)
        
        if resp2.error:
            return []
            
        try:
            parsed_out2 = schema_model.model_validate_json(resp2.content)
            return getattr(parsed_out2, "records", [])
        except ValidationError as e2:
            logger.error(f"Failed LLM extraction validation twice: {e2}")
            return []

def extract_document(doc_id: str, run_id: str) -> None:
    conn = connect()
    doc_row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", [doc_id]).fetchone()
    if not doc_row:
        conn.close()
        return
        
    doc = dict(doc_row)
    
    parsed = load_parsed(doc_id)
    if not parsed:
        conn.close()
        return
        
    pages = parsed.get("pages", [])
    tables = parsed.get("tables", [])
    
    sections = conn.execute("SELECT kind, page_start, page_end FROM sections WHERE doc_id = ?", [doc_id]).fetchall()
    
    conn.execute(
        "INSERT OR IGNORE INTO extraction_runs (run_id, started_at, model, prompt_version, git_commit) VALUES (?, datetime('now'), ?, ?, ?)",
        [run_id, "groq:llama3-70b", "v1", "HEAD"]
    )
    
    for section_row in sections:
        kind, page_start, page_end = section_row
        for task in SECTION_TO_TASK.get(kind, []):
            sec_pages = [p for p in pages if page_start <= p["page_no"] <= page_end]
            
            for window in page_windows(sec_pages, max_tokens=4000):
                recs = []
                if task == "shareholding":
                    window_page_nos = [p["page_no"] for p in window]
                    window_tables = [t for t in tables if t["page_no"] in window_page_nos]
                    
                    for t in window_tables:
                        from datetime import date
                        r = parse_shareholding_table(doc_id, doc.get("company_id", ""), t["page_no"], t["cells"], date.today())
                        if r:
                            recs.extend(r)
                            
                    if not recs:
                        recs = llm_extract(task, doc, window)
                else:
                    recs = llm_extract(task, doc, window)
                    
                for rec in recs:
                    status, reason = check(rec, parsed)
                    payload_json = rec.model_dump_json() if hasattr(rec, "model_dump_json") else "{}"
                    record_id = str(uuid.uuid4())
                    
                    conn.execute(
                        "INSERT INTO records (record_id, run_id, doc_id, record_type, payload_json, status, reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [record_id, run_id, doc_id, task, payload_json, status, reason or ""]
                    )
                    
                    if status == "review":
                        conn.execute(
                            "INSERT INTO review_queue (record_id, reason, created_at) VALUES (?, ?, datetime('now'))",
                            [record_id, reason or ""]
                        )
                        
    conn.execute("UPDATE documents SET status = 'extracted' WHERE doc_id = ?", [doc_id])
    conn.execute("UPDATE extraction_runs SET finished_at = datetime('now') WHERE run_id = ?", [run_id])
    conn.commit()
    conn.close()

def extract_all(run_id: str) -> None:
    conn = connect()
    rows = conn.execute("SELECT doc_id FROM documents WHERE status = 'parsed'").fetchall()
    conn.close()
    
    for (doc_id,) in rows:
        print(f"Extracting records for document {doc_id}...")
        extract_document(doc_id, run_id)
        
    print(f"Extraction complete for run {run_id}.")
