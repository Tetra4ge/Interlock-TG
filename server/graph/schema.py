import glob
import hashlib
import json
import logging
import os

from server.graph.client import get_tg_connection
from server.graph.names import rewrite_gsql

logger = logging.getLogger(__name__)


def apply_schema() -> None:
    conn = get_tg_connection()

    # Check if graph exists by looking for vertex types
    try:
        types = conn.getVertexTypes()
        if types:
            logger.info("Graph already has vertex types. Skipping schema creation.")
            return
    except Exception:
        pass

    logger.info("Applying schema.gsql...")
    with open("server/graph/gsql/schema.gsql") as f:
        schema = rewrite_gsql(f.read(), conn.graphname)

    out = conn.gsql(schema)
    logger.info(f"Schema applied: {out}")


def install_queries() -> None:
    conn = get_tg_connection()
    query_dir = "server/graph/gsql/queries"
    lock_file = "server/graph/gsql/queries.lock"

    if not os.path.exists(query_dir):
        return

    query_files = glob.glob(f"{query_dir}/*.gsql")
    if not query_files:
        return

    locks = {}
    if os.path.exists(lock_file):
        with open(lock_file) as f:
            locks = json.load(f)

    changed = False
    new_locks = {}

    # Hash the text that is actually installed, so a change of graph name also triggers it.
    rewritten = {}
    for qf in query_files:
        with open(qf) as f:
            rewritten[qf] = rewrite_gsql(f.read(), conn.graphname)

    for qf in query_files:
        h = hashlib.sha256(rewritten[qf].encode()).hexdigest()
        new_locks[qf] = h
        if locks.get(qf) != h:
            changed = True

    if not changed:
        logger.info("No queries changed, skipping installation.")
        return

    logger.info("Queries changed, installing (this takes a few minutes compiling C++)...")
    # GSQL needs a graph selected before INSTALL QUERY, or the install fails.
    combined = f"USE GRAPH {conn.graphname}\n"
    for qf in query_files:
        combined += rewritten[qf] + "\n"

    combined += "INSTALL QUERY ALL\n"
    out = conn.gsql(combined)
    logger.info(f"Queries installed: {out}")

    # The install can "succeed" at the gsql() call level while individual queries are rejected
    # as drafts (syntax/semantic errors) -- only persist the lock when nothing failed, so a
    # broken query is retried on the next run instead of being silently skipped forever.
    failure_markers = ("Failed to create queries", "draft query with type/semantic error")
    if any(m in out for m in failure_markers):
        logger.error("Some queries failed to install; lock file left unchanged so they retry.")
        return

    with open(lock_file, "w") as f:
        json.dump(new_locks, f)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    apply_schema()
    install_queries()
