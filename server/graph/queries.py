import logging
import re
from typing import Any

from rapidfuzz import fuzz

from server.embed.index import search_vector_index
from server.embed.keyword import keyword_search, load_chunks
from server.graph.client import get_tg_connection
from server.pipelines.common.fusion import reciprocal_rank_fusion
from server.store.db import connect

logger = logging.getLogger(__name__)


class GraphQueryError(RuntimeError):
    """An installed GSQL query failed (timeout, not installed, bad params).
    Distinct from an empty result so callers can retry or fall back."""


def run_installed_strict(query_name: str, params: dict, timeout_s: int | None = None) -> Any:
    conn = get_tg_connection()
    try:
        return conn.runInstalledQuery(
            query_name, params=params, timeout=None if timeout_s is None else timeout_s * 1000
        )
    except Exception as e:
        raise GraphQueryError(f"{query_name}: {e}") from e


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


def _fts_query(text: str) -> str:
    """Quoted phrase-prefix, plus every token as an AND-ed prefix for multi-token
    names. Everything is quoted so FTS5 syntax characters in a name cannot break
    the query; fuzziness comes from the RapidFuzz re-rank, not the index."""
    safe = text.replace('"', '""')
    phrase = f'"{safe}"*'
    tokens = [t for t in re.findall(r"\w+", text) if len(t) > 1]
    if len(tokens) < 2:
        return phrase
    anded = " AND ".join('"' + t + '"*' for t in tokens)
    return f"{phrase} OR ({anded})"


def entity_search(text: str, kind: str | None = None, limit: int = 5) -> list[dict]:
    db = connect()
    where = "entities_fts MATCH ?"
    params: list[str] = [_fts_query(text)]
    if kind:
        where += " AND kind = ?"
        params.append(kind)

    try:
        try:
            rows = db.execute(
                "SELECT entity_id, canonical_name, aliases_text, kind "
                f"FROM entities_fts WHERE {where} LIMIT 100",
                params,
            ).fetchall()
        except Exception as e:
            # FTS table might not exist if build-graph hasn't run the entity-index step
            logger.warning(f"FTS query failed: {e}. Falling back to full scan.")
            q = "SELECT entity_id, canonical_name, aliases_text, kind FROM entities"
            if kind:
                q += " WHERE kind = ?"
                rows = db.execute(q, [kind]).fetchall()
            else:
                rows = db.execute(q).fetchall()
    finally:
        db.close()

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
            {
                "entity_id": eid,
                "canonical_name": canon,
                "kind": r_kind,
                "score": best_score,
                "names": [n for n in names if n],
            }
        )

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:limit]


def entity_names(entity_ids: list[str]) -> dict[str, tuple[str, str]]:
    """entity_id -> (canonical_name, kind) for the ids that exist in Turso."""
    if not entity_ids:
        return {}
    db = connect()
    try:
        marks = ",".join("?" * len(entity_ids))
        rows = db.execute(
            f"SELECT entity_id, canonical_name, kind FROM entities WHERE entity_id IN ({marks})",
            list(entity_ids),
        ).fetchall()
    finally:
        db.close()
    return {r[0]: (r[1], r[2]) for r in rows}


_VERTEX_TYPE_BY_PREFIX = {"C:": "Company", "P:": "Person", "A:": "AuditFirm"}


def vertex_param(entity_id: str) -> tuple[str, str]:
    """(id, vertex_type) for a query parameter declared as untyped VERTEX. A bare
    id string is encoded without its type, which TigerGraph rejects."""
    for prefix, vertex_type in _VERTEX_TYPE_BY_PREFIX.items():
        if entity_id.startswith(prefix):
            return entity_id, vertex_type
    raise ValueError(f"Cannot infer a vertex type from entity id {entity_id!r}")


def neighbors(
    entity_id: str, rel_types: list[str] | None = None, hops: int = 1, fy: str = ""
) -> Any:
    return run_installed(
        "entity_neighbors",
        {"seeds": [vertex_param(entity_id)], "hops": hops, "fiscal_year": fy},
    )


def shared_directors(ids: list[str], fy: str = "") -> Any:
    return run_installed("shared_directors", {"companies": ids, "fiscal_year": fy})


def path_between(a: str, b: str, max_hops: int = 3) -> Any:
    return run_installed(
        "path_between",
        {"source": vertex_param(a), "target": vertex_param(b), "max_hops": max_hops},
    )


def aggregate_stake(entity_id: str) -> Any:
    return run_installed("stake_aggregate", {"company": entity_id})


def chunks_for_entities(ids: list[str], limit: int = 10) -> Any:
    return run_installed(
        "chunks_for_entities",
        {"entities": [vertex_param(i) for i in ids], "max_limit": limit},
    )


def chunks_for_entities_strict(ids: list[str], limit: int, timeout_s: int | None = None) -> Any:
    """Same query, but a failure raises GraphQueryError instead of reading as no chunks."""
    return run_installed_strict(
        "chunks_for_entities",
        {"entities": [vertex_param(i) for i in ids], "max_limit": limit},
        timeout_s,
    )


def get_chunk(chunk_id: str) -> dict:
    conn = get_tg_connection()
    res = conn.getVerticesById("Chunk", [chunk_id])
    return res[0] if res else {}


def get_edge(edge_id: str) -> dict:
    # Use our deployed GSQL query to scan fact edges for the discriminator
    return run_installed("get_edge_by_id", {"edge_id": edge_id})
