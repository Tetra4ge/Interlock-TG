import json
import logging
from pathlib import Path

import pyTigerGraph as tg

from server.graph.client import get_tg_connection
from server.parse.clean import normalize_for_match
from server.store.db import connect

logger = logging.getLogger(__name__)

CHUNKS_DIR = Path("data/chunks")

def batched_upsert_edges(
    conn: tg.TigerGraphConnection, 
    src_type: str, 
    e_type: str, 
    tgt_type: str, 
    rows: list[tuple[str, str, dict]], 
    batch_size: int = 500
) -> None:
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i+batch_size]
        conn.upsertEdges(src_type, e_type, tgt_type, batch)

def run_mentions_link() -> None:
    logger.info("Initializing Mentions Linker...")
    tg_conn = get_tg_connection()
    db = connect()
    
    # 1. Load entities and aliases
    logger.info("Loading entities and constructing search phrases...")
    entities = db.execute(
        "SELECT entity_id, kind, canonical_name, aliases_text FROM entities"
    ).fetchall()
    
    entity_kind: dict[str, str] = {}
    search_phrases: dict[str, set[str]] = {}
    
    for eid, kind, canon, aliases_text in entities:
        tgt_kind = kind.title()
        if tgt_kind == "Audit_firm" or tgt_kind == "Auditfirm": 
            tgt_kind = "AuditFirm"
        entity_kind[eid] = tgt_kind
        
        phrases = [canon]
        if aliases_text:
            phrases.extend(aliases_text.split("|"))
            
        for p in phrases:
            if not p:
                continue
            norm_p = normalize_for_match(p)
            if len(norm_p.split()) >= 2:  # skip single-token aliases
                if norm_p not in search_phrases:
                    search_phrases[norm_p] = set()
                search_phrases[norm_p].add(eid)

    # 2. Load records for overlap matching
    logger.info("Mapping records to document pages...")
    records = db.execute("""
        SELECT r.record_id, r.doc_id, r.payload_json
        FROM records r
        WHERE r.status = 'accepted' OR r.status = 'fixed'
    """).fetchall()

    record_pages = {
        rec_id: (doc_id, json.loads(payload_json).get("page"))
        for rec_id, doc_id, payload_json in records
    }
    
    mlog = db.execute("SELECT mention_id, entity_id FROM merge_log").fetchall()
    
    # doc_id -> page_num -> set(entity_ids)
    page_entities: dict[str, dict[int, set[str]]] = {}
    
    for mention_id, eid in mlog:
        record_id = mention_id.split(":")[0]
        if record_id in record_pages:
            doc_id, page_num = record_pages[record_id]
            if not page_num:
                page_num = 0
            if doc_id not in page_entities:
                page_entities[doc_id] = {}
            if page_num not in page_entities[doc_id]:
                page_entities[doc_id][page_num] = set()
            page_entities[doc_id][page_num].add(eid)
            
    # 3. Load chunks and link
    # Chunks live as data/chunks/{doc_id}_chunks.json (written by chunk_all()),
    # not a SQLite table -- there is no `chunks` table in the schema.
    logger.info("Evaluating MENTIONS across all chunks...")
    doc_ids = [row[0] for row in db.execute("SELECT doc_id FROM documents").fetchall()]
    chunks = []
    for doc_id in doc_ids:
        chunk_file = CHUNKS_DIR / f"{doc_id}_chunks.json"
        if not chunk_file.exists():
            continue
        for c in json.loads(chunk_file.read_text()):
            chunks.append(
                (c["chunk_id"], doc_id, c["text"], c["page_start"], c["page_end"])
            )
    
    mentions_company = []
    mentions_person = []
    mentions_auditfirm = []
    
    linked_chunk_ids = set()
    
    for chunk_id, doc_id, text, page_start, page_end in chunks:
        found_entities = set()
        
        # Rule 1: Precise overlap
        if doc_id in page_entities:
            p_start = page_start or 0
            p_end = page_end or p_start
            for p in range(p_start, p_end + 1):
                if p in page_entities[doc_id]:
                    found_entities.update(page_entities[doc_id][p])
                    
        # Rule 2: String match
        if text:
            norm_text = normalize_for_match(text)
            for phrase, eids in search_phrases.items():
                if phrase in norm_text:
                    found_entities.update(eids)
                
        for eid in found_entities:
            linked_chunk_ids.add(chunk_id)
            tgt = entity_kind.get(eid)
            if tgt == "Company":
                mentions_company.append((chunk_id, eid, {}))
            elif tgt == "Person":
                mentions_person.append((chunk_id, eid, {}))
            elif tgt == "AuditFirm":
                mentions_auditfirm.append((chunk_id, eid, {}))
                
    # 4. Upsert MENTIONS edges
    batched_upsert_edges(tg_conn, "Chunk", "MENTIONS", "Company", mentions_company)
    batched_upsert_edges(tg_conn, "Chunk", "MENTIONS", "Person", mentions_person)
    batched_upsert_edges(tg_conn, "Chunk", "MENTIONS", "AuditFirm", mentions_auditfirm)
    
    total = len(chunks)
    linked = len(linked_chunk_ids)
    pct = (linked/total*100) if total > 0 else 0
    logger.info(f"GraphRAG MENTIONS Coverage: {linked}/{total} chunks linked ({pct:.1f}%)")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_mentions_link()
