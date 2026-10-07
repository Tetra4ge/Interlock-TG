import numpy as np

from server.store.db import connect

# Mentions per entity in the resolver's merge_log. Every accepted record that
# became a fact edge contributes one mention per endpoint, so this is the fact-edge
# degree used to spot hub nodes (the MENTIONS edges to chunks are deliberately not
# counted: expansion never walks them).


def entity_degrees() -> dict[str, int]:
    db = connect()
    try:
        rows = db.execute("SELECT entity_id, COUNT(*) FROM merge_log GROUP BY entity_id").fetchall()
    finally:
        db.close()
    return {r[0]: int(r[1]) for r in rows}


def hub_ids(percentile: float, min_degree: int) -> set[str]:
    """Entities whose fact-edge degree is above both the given percentile and an
    absolute floor. The floor stops tiny graphs flagging their busiest entity."""
    degrees = entity_degrees()
    if not degrees:
        return set()
    threshold = max(float(np.percentile(list(degrees.values()), percentile)), float(min_degree))
    return {eid for eid, d in degrees.items() if d > threshold}
