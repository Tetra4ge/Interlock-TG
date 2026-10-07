import json
from typing import Any

from server.api.schemas import ReviewItem

DEFAULT_LIMIT = 100


def pending_reviews(conn: Any, limit: int = DEFAULT_LIMIT) -> list[ReviewItem]:
    """Records waiting for a human decision, oldest first. Read-only: decisions are
    made with `hl review`, which also keeps the audit trail."""
    rows = conn.execute(
        """
        SELECT q.record_id, COALESCE(r.record_type, ''), q.reason, q.created_at,
               d.company_id, d.fiscal_year, r.payload_json
        FROM review_queue q
        LEFT JOIN records r ON r.record_id = q.record_id
        LEFT JOIN documents d ON d.doc_id = r.doc_id
        WHERE q.decided_at IS NULL
        ORDER BY q.created_at, q.record_id
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    items = []
    for record_id, rtype, reason, created, company, fy, payload_json in rows:
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except json.JSONDecodeError:
            payload = {}
        items.append(
            ReviewItem(
                record_id=record_id,
                record_type=rtype,
                reason=reason,
                created_at=created,
                company_id=company,
                fiscal_year=fy,
                payload=payload if isinstance(payload, dict) else {},
            )  # fmt: skip
        )
    return items
