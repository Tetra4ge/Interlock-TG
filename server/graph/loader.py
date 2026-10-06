import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import pyTigerGraph as tg

from server.graph.client import get_tg_connection
from server.store.db import connect

CHUNKS_DIR = Path("data/chunks")

logger = logging.getLogger(__name__)


def batched_upsert_vertices(
    conn: tg.TigerGraphConnection, v_type: str, rows: list[tuple[str, dict]], batch_size: int = 500
) -> None:
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        try:
            conn.upsertVertices(v_type, batch)
            logger.info(f"Upserted {len(batch)} {v_type} vertices.")
        except Exception as e:
            logger.error(
                f"Failed to upsert {v_type} batch. Error: {e}. Row IDs: {[r[0] for r in batch]}"
            )


def batched_upsert_edges(
    conn: tg.TigerGraphConnection,
    src_type: str,
    e_type: str,
    tgt_type: str,
    rows: list[tuple[str, str, dict]],
    batch_size: int = 500,
) -> None:
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        try:
            conn.upsertEdges(src_type, e_type, tgt_type, batch)
            logger.info(f"Upserted {len(batch)} {e_type} edges ({src_type}->{tgt_type}).")
        except Exception as e:
            logger.error(
                f"Failed to upsert {e_type} batch. Error: {e}. "
                f"Edge endpoints: {[(r[0], r[1]) for r in batch]}"
            )


def load_graph(run_id: str = "default-run") -> None:
    logger.info("Initializing Graph Loader...")
    tg = get_tg_connection()
    db = connect()

    logger.info("Extracting Entities from DB...")
    entities = db.execute(
        "SELECT entity_id, kind, canonical_name, aliases_text FROM entities"
    ).fetchall()

    companies = []
    persons = []
    audit_firms = []

    for row in entities:
        eid, kind, name, aliases = row
        if kind == "company":
            # Heuristic for dataset membership. Could also check against companies.yaml
            in_ds = not eid.startswith("C:x")
            companies.append((eid, {"name": name, "aliases_text": aliases, "in_dataset": in_ds}))
        elif kind == "person":
            persons.append((eid, {"name": name, "aliases_text": aliases}))
        elif kind == "audit_firm":
            audit_firms.append((eid, {"name": name, "aliases_text": aliases}))

    logger.info("1/3 Upserting Core Vertices (Companies, Persons, AuditFirms)...")
    batched_upsert_vertices(tg, "Company", companies)
    batched_upsert_vertices(tg, "Person", persons)
    batched_upsert_vertices(tg, "AuditFirm", audit_firms)

    logger.info("2/3 Upserting Document Vertices...")
    docs = db.execute("SELECT doc_id FROM documents").fetchall()
    batched_upsert_vertices(tg, "Document", [(d[0], {}) for d in docs])

    logger.info("Processing Edge Relationships from Records...")
    records = db.execute("""
        SELECT r.record_id, r.record_type, r.payload_json, r.doc_id, d.company_id, d.fiscal_year
        FROM records r
        JOIN documents d ON r.doc_id = d.doc_id
        WHERE r.status = 'accepted' OR r.status = 'fixed'
    """).fetchall()

    mlog = db.execute("SELECT mention_id, entity_id FROM merge_log").fetchall()
    mention_to_entity = {m[0]: m[1] for m in mlog}
    entity_kinds = {row[0]: row[1] for row in entities}

    director_edges = []
    rpt_vertices = []
    party_to_edges = []
    audited_by_edges: list[Any] = []

    for row in records:
        rec_id, rec_type, payload_json, doc_id, ctx_cid, fiscal_year = row
        payload = json.loads(payload_json)
        # Provenance lives under the record's evidence, not at the top level.
        evidence = payload.get("evidence") or {}
        page_num = evidence.get("page") or 0
        quote = evidence.get("quote") or ""

        ctx_mention_id = f"{rec_id}:context_company"
        ctx_eid = mention_to_entity.get(ctx_mention_id)

        if rec_type == "directors":
            person_mention_id = f"{rec_id}:person"
            person_eid = mention_to_entity.get(person_mention_id)
            if not person_eid or not ctx_eid:
                continue

            edge_id = hashlib.sha256(f"{rec_id}:DIRECTOR_OF".encode()).hexdigest()[:16]
            attrs = {
                "edge_id": edge_id,
                "role": payload.get("role", ""),
                "independent": payload.get("is_independent", False),
                "start_date": payload.get("appointed_on") or "",
                "end_date": payload.get("ceased_on") or "",
                "fiscal_year": payload.get("fiscal_year") or fiscal_year or "",
                "doc_id": doc_id,
                "page": page_num,
                "quote": quote,
                "run_id": run_id,
            }
            director_edges.append((person_eid, ctx_eid, attrs))

        elif rec_type == "rpt":
            cp_mention_id = f"{rec_id}:counterparty"
            cp_eid = mention_to_entity.get(cp_mention_id)
            if not cp_eid or not ctx_eid:
                continue

            txn_id = hashlib.sha256(rec_id.encode()).hexdigest()[:16]
            rpt_vertices.append(
                (
                    txn_id,
                    {
                        "amount_inr": float(payload.get("amount_inr") or 0.0),
                        "nature": payload.get("nature", ""),
                        "relationship": payload.get("relationship", ""),
                        "fiscal_year": payload.get("fiscal_year") or fiscal_year or "",
                    },
                )
            )

            # 1. Reporting side edge
            edge_id_ctx = hashlib.sha256(f"{rec_id}:PARTY_TO:reporting".encode()).hexdigest()[:16]
            party_to_edges.append(
                (
                    ctx_eid,
                    txn_id,
                    {
                        "side": "reporting",
                        "doc_id": doc_id,
                        "page": page_num,
                        "quote": quote,
                        "run_id": run_id,
                        "edge_id": edge_id_ctx,
                    },
                    "Company",
                )
            )

            # 2. Counterparty side edge
            edge_id_cp = hashlib.sha256(f"{rec_id}:PARTY_TO:counterparty".encode()).hexdigest()[:16]
            cp_kind = entity_kinds.get(cp_eid, "company").title()  # "Company" or "Person"
            if cp_kind == "Audit_Firm":
                cp_kind = "AuditFirm"

            party_to_edges.append(
                (
                    cp_eid,
                    txn_id,
                    {
                        "side": "counterparty",
                        "doc_id": doc_id,
                        "page": page_num,
                        "quote": quote,
                        "run_id": run_id,
                        "edge_id": edge_id_cp,
                    },
                    cp_kind,
                )
            )

        elif rec_type == "auditor":
            af_mention_id = f"{rec_id}:audit_firm"
            af_eid = mention_to_entity.get(af_mention_id)
            if not af_eid or not ctx_eid:
                continue

            audited_by_edges.append((ctx_eid, af_eid, {}))

    logger.info("3/3 Upserting RPT Vertices and all Edge Relationships...")
    batched_upsert_vertices(tg, "RelatedPartyTxn", rpt_vertices)

    batched_upsert_edges(tg, "Person", "DIRECTOR_OF", "Company", director_edges)
    batched_upsert_edges(tg, "Company", "AUDITED_BY", "AuditFirm", audited_by_edges)

    # PARTY_TO requires separation by src_type since it can be Person or Company
    party_to_company = [
        (src, tgt, attr) for (src, tgt, attr, kind) in party_to_edges if kind == "Company"
    ]
    party_to_person = [
        (src, tgt, attr) for (src, tgt, attr, kind) in party_to_edges if kind == "Person"
    ]

    batched_upsert_edges(tg, "Company", "PARTY_TO", "RelatedPartyTxn", party_to_company)
    batched_upsert_edges(tg, "Person", "PARTY_TO", "RelatedPartyTxn", party_to_person)
    logger.info("4/4 Upserting Chunks into the Graph...")
    # Chunks live as data/chunks/{doc_id}_chunks.json (written by chunk_all()),
    # not a SQLite table -- there is no `chunks` table in the schema.
    chunk_vertices = []
    has_chunk_edges: list[Any] = []
    for (doc_id,) in docs:
        chunk_file = CHUNKS_DIR / f"{doc_id}_chunks.json"
        if not chunk_file.exists():
            continue
        for c in json.loads(chunk_file.read_text()):
            chunk_vertices.append(
                (
                    c["chunk_id"],
                    {
                        "doc_id": doc_id,
                        "text": c["text"],
                        "section": c["section"],
                        "page_start": c["page_start"],
                        "page_end": c["page_end"],
                        "fiscal_year": c.get("fiscal_year") or "",
                        "company_id": c.get("company_id") or "",
                    },
                )
            )
            has_chunk_edges.append((doc_id, c["chunk_id"], {}))

    batched_upsert_vertices(tg, "Chunk", chunk_vertices)
    batched_upsert_edges(tg, "Document", "HAS_CHUNK", "Chunk", has_chunk_edges)

    logger.info("TigerGraph Load Complete!")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    load_graph()
