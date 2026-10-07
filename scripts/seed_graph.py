"""Import the sample graph into TigerGraph on first start.

Runs only when SEED_GRAPH=true (see scripts/entrypoint.sh). It is a no-op when the sample
export is absent or the graph already holds data, so it is safe to run on every start.
"""

import logging
import sys
import time

from server.graph.client import get_tg_connection
from server.graph.export import EXPORT_DIR, import_sample

logger = logging.getLogger("seed_graph")

ATTEMPTS = 40
DELAY_SECONDS = 15


def wait_for_tigergraph() -> object:
    # The first start of the TigerGraph container can take several minutes.
    for attempt in range(1, ATTEMPTS + 1):
        try:
            conn = get_tg_connection()
            conn.echo()
            return conn
        except Exception as e:
            logger.info("TigerGraph not ready (attempt %d/%d): %s", attempt, ATTEMPTS, e)
            time.sleep(DELAY_SECONDS)
    raise RuntimeError("TigerGraph did not become ready in time")


def graph_is_populated(conn: object) -> bool:
    try:
        return int(conn.getVertexCount("Company")) > 0  # type: ignore[attr-defined]
    except Exception:
        return False


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    if not (EXPORT_DIR / "vertices.jsonl").exists() or not (EXPORT_DIR / "edges.jsonl").exists():
        logger.warning("No sample graph export in %s; skipping seed", EXPORT_DIR)
        return 0
    conn = wait_for_tigergraph()
    if graph_is_populated(conn):
        logger.info("Graph already holds data; skipping seed")
        return 0
    import_sample()
    return 0


if __name__ == "__main__":
    sys.exit(main())
