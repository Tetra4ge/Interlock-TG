import json
import logging
from typing import Any

from server.api.schemas import DataQualityOut

logger = logging.getLogger(__name__)

NOTE = (
    "Computed from the local run store (documents, records, entities). Provenance counts "
    "accepted records that carry a quoted evidence page; it is measured, not assumed."
)


def _count(conn: Any, sql: str) -> int:
    try:
        return int(conn.execute(sql).fetchone()[0])
    except Exception as e:
        logger.warning(f"data-quality query failed ({sql[:50]}...): {e}")
        return 0


def _grouped(conn: Any, sql: str) -> dict[str, int]:
    try:
        return {str(k): int(v) for k, v in conn.execute(sql).fetchall()}
    except Exception as e:
        logger.warning(f"data-quality query failed ({sql[:50]}...): {e}")
        return {}


def _has_provenance(payload: dict[str, Any]) -> bool:
    evidence = payload.get("evidence")
    return isinstance(evidence, dict) and bool(evidence.get("quote")) and bool(evidence.get("page"))


def provenance_complete_pct(conn: Any) -> float | None:
    try:
        rows = conn.execute(
            "SELECT payload_json FROM records WHERE status IN ('accepted', 'fixed')"
        ).fetchall()
    except Exception as e:
        logger.warning(f"provenance query failed: {e}")
        return None
    if not rows:
        return None
    complete = sum(_has_provenance(json.loads(r[0])) for r in rows)
    return round(100.0 * complete / len(rows), 1)


def data_quality(conn: Any) -> DataQualityOut:
    return DataQualityOut(
        documents=_count(conn, "SELECT COUNT(*) FROM documents"),
        documents_parsed=_count(
            conn, "SELECT COUNT(*) FROM documents WHERE status IN ('parsed', 'extracted')"
        ),
        documents_failed=_count(conn, "SELECT COUNT(*) FROM documents WHERE status = 'failed'"),
        companies=_count(
            conn,
            "SELECT COUNT(DISTINCT d.company_id) FROM documents d JOIN records r "
            "ON r.doc_id = d.doc_id WHERE r.status IN ('accepted', 'fixed')",
        ),
        records_total=_count(conn, "SELECT COUNT(*) FROM records"),
        records_accepted=_count(conn, "SELECT COUNT(*) FROM records WHERE status = 'accepted'"),
        records_rejected=_count(conn, "SELECT COUNT(*) FROM records WHERE status = 'rejected'"),
        review_queue=_count(conn, "SELECT COUNT(*) FROM review_queue"),
        entities_by_kind=_grouped(conn, "SELECT kind, COUNT(*) FROM entities GROUP BY kind"),
        mentions_by_method=_grouped(conn, "SELECT method, COUNT(*) FROM merge_log GROUP BY method"),
        provenance_complete_pct=provenance_complete_pct(conn),
        note=NOTE,
    )
