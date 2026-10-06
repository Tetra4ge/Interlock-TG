import logging
from typing import Any

from rapidfuzz import fuzz

from server.embed.index import search_vector_index
from server.embed.keyword import keyword_search, load_chunks
from server.graph.client import get_tg_connection
from server.pipelines.common.fusion import reciprocal_rank_fusion
from server.store.db import connect

logger = logging.getLogger(__name__)


def run_installed(query_name: str, params: dict) -> Any:
    conn = get_tg_connection()
    try:
        return conn.runInstalledQuery(query_name, params=params)
    except Exception as e:
        logger.error(f"Error running GSQL {query_name}: {e}")
        return []


def _allowed_doc_ids(filters: dict) -> list[str] | None:
    clauses, params = [], []
    for key in ("company_id", "fiscal_year"):
        if key in filters:
            clauses.append(f"{key} = ?")
            params.append(filters[key])
    if not clauses:
        return None
    conn = connect()
    try:
        rows = conn.execute(
            f"SELECT doc_id FROM documents WHERE {' AND '.join(clauses)}", params
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def vector_search(query: str, k: int = 10, filters: dict | None = None) -> list[dict]:
    filters = filters or {}
    doc_ids = _allowed_doc_ids(filters)
    # 1. Candidates from the vector index and BM25 keyword search, both restricted to the
    #    filtered documents before ranking; fused so exact phrases can surface too.
    vector_hits = search_vector_index(
        query,
        k=k * 3,
        allowed_doc_prefixes=None if doc_ids is None else {d[:12] for d in doc_ids},
    )
    keyword_hits = keyword_search(query, load_chunks(doc_ids), k=k * 3)
    raw_results = reciprocal_rank_fusion([vector_hits, keyword_hits], k_out=k * 3)
    if not raw_results:
        return []

    # 2. Chunk text and attributes come from the local chunk files, not from
    #    TigerGraph. getVerticesById issues one HTTPS round-trip per id
    #    (pyTigerGraph loops over the ids), so fetching k*3 chunks from a
    #    cloud instance added tens of seconds per query; the same chunks the
    #    vector/keyword index was built from are already on disk.
    chunk_by_id = {str(c["chunk_id"]): c for c in load_chunks(doc_ids)}

    final_results = []
    for cid, score in raw_results:
        chunk = chunk_by_id.get(cid)
        if not chunk:
            continue

        if "fiscal_year" in filters and chunk.get("fiscal_year") != filters["fiscal_year"]:
            continue
        if "company_id" in filters and chunk.get("company_id") != filters["company_id"]:
            continue

        final_results.append({**chunk, "chunk_id": cid, "score": score})
        if len(final_results) >= k:
            break

    return final_results


def entity_search(text: str, kind: str | None = None, limit: int = 5) -> list[dict]:
    # FTS5 search then RapidFuzz
    db = connect()

    # Escape simple FTS characters (just quoting for now)
    safe_text = text.replace('"', '""')
    fts_query = f'"{safe_text}"*'

    where = "entities_fts MATCH ?"
    params = [fts_query]

    if kind:
        where += " AND kind = ?"
        params.append(kind)

    try:
        rows = db.execute(
            "SELECT entity_id, canonical_name, aliases_text, kind "
            f"FROM entities_fts WHERE {where} LIMIT 100",
            params,
        ).fetchall()
    except Exception as e:
        # FTS table might not exist if build-graph hasn't run Step 14
        logger.warning(f"FTS query failed: {e}. Falling back to full scan.")
        q = "SELECT entity_id, canonical_name, aliases_text, kind FROM entities"
        if kind:
            q += " WHERE kind = ?"
            rows = db.execute(q, [kind]).fetchall()
        else:
            rows = db.execute(q).fetchall()

    candidates = []
    for r in rows:
        eid, canon, aliases, r_kind = r
        names = [canon]
        if aliases:
            names.extend(aliases.split("|"))

        best_score = max(
            (fuzz.token_sort_ratio(text.lower(), n.lower()) for n in names if n), default=0
        )
        candidates.append(
            {"entity_id": eid, "canonical_name": canon, "kind": r_kind, "score": best_score}
        )

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:limit]


def neighbors(
    entity_id: str, rel_types: list[str] | None = None, hops: int = 1, fy: str = ""
) -> Any:
    return run_installed(
        "entity_neighbors", {"seeds": [entity_id], "hops": hops, "fiscal_year": fy}
    )


def shared_directors(ids: list[str], fy: str = "") -> Any:
    return run_installed("shared_directors", {"companies": ids, "fiscal_year": fy})


def path_between(a: str, b: str, max_hops: int = 3) -> Any:
    return run_installed("path_between", {"source": a, "target": b, "max_hops": max_hops})


def aggregate_stake(entity_id: str) -> Any:
    return run_installed("stake_aggregate", {"company": entity_id})


def chunks_for_entities(ids: list[str], limit: int = 10) -> Any:
    return run_installed("chunks_for_entities", {"entities": ids, "max_limit": limit})


def get_chunk(chunk_id: str) -> dict:
    conn = get_tg_connection()
    res = conn.getVerticesById("Chunk", [chunk_id])
    return res[0] if res else {}


def get_edge(edge_id: str) -> dict:
    # Use our deployed GSQL query to scan fact edges for the discriminator
    return run_installed("get_edge_by_id", {"edge_id": edge_id})
