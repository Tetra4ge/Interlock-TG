import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from server.graph.client import get_tg_connection

logger = logging.getLogger(__name__)

EXPORT_DIR = Path("data/sample_graph")


def export_sample(limit: int = 15) -> None:
    logger.info(f"Exporting sample graph (limit={limit})...")
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_tg_connection()

    # We use an interpreted query to easily grab a localized subgraph
    # around a sample of companies and their 1-hop neighbors (Chunks, Persons, etc).
    query = f"""
      SetAccum<VERTEX> @@vertices;
      SetAccum<EDGE> @@edges;
      
      C = SELECT c FROM Company:c LIMIT {limit};
      @@vertices += C;
      
      N1 = SELECT t FROM C:s -(:e)- :t 
           ACCUM @@edges += e, @@vertices += t;
           
      PRINT @@vertices;
      PRINT @@edges;
    """

    try:
        results = conn.runInterpretedQuery(query)
    except Exception as e:
        logger.error(
            f"Interpreted query failed "
            f"(ensure your TigerGraph edition supports interpreted queries): {e}"
        )
        return

    vertices = []
    edges = []
    for r in results:
        if "@@vertices" in r:
            vertices = r["@@vertices"]
        if "@@edges" in r:
            edges = r["@@edges"]

    with open(EXPORT_DIR / "vertices.jsonl", "w") as vf:
        for v in vertices:
            record = {"vertex_type": v["v_type"], "id": v["v_id"], "attrs": v["attributes"]}
            vf.write(json.dumps(record) + "\n")

    with open(EXPORT_DIR / "edges.jsonl", "w") as ef:
        for edge in edges:
            record = {
                "edge_type": edge["e_type"],
                "src_type": edge["from_type"],
                "src_id": edge["from_id"],
                "tgt_type": edge["to_type"],
                "tgt_id": edge["to_id"],
                "attrs": edge["attributes"],
            }
            ef.write(json.dumps(record) + "\n")

    logger.info(f"Exported {len(vertices)} vertices and {len(edges)} edges to {EXPORT_DIR}")


def import_sample() -> None:
    logger.info("Importing sample graph...")
    conn = get_tg_connection()

    v_file = EXPORT_DIR / "vertices.jsonl"
    e_file = EXPORT_DIR / "edges.jsonl"

    if not v_file.exists() or not e_file.exists():
        logger.error(f"Sample graph files not found in {EXPORT_DIR}")
        return

    # Batch data by type for efficient pyTigerGraph upsert
    v_batches: defaultdict[str, list[Any]] = defaultdict(list)
    e_batches: defaultdict[tuple[str, str, str], list[Any]] = defaultdict(list)

    with open(v_file) as f:
        for line in f:
            data = json.loads(line)
            v_batches[data["vertex_type"]].append((data["id"], data["attrs"]))

    with open(e_file) as f:
        for line in f:
            data = json.loads(line)
            e_batches[(data["src_type"], data["edge_type"], data["tgt_type"])].append(
                (data["src_id"], data["tgt_id"], data["attrs"])
            )

    logger.info("Upserting vertices...")
    for v_type, rows in v_batches.items():
        conn.upsertVertices(v_type, rows)

    logger.info("Upserting edges...")
    for (s_type, e_type, t_type), rows in e_batches.items():
        conn.upsertEdges(s_type, e_type, t_type, rows)

    logger.info(
        f"Import complete! Recreated "
        f"{sum(len(r) for r in v_batches.values())} vertices and "
        f"{sum(len(r) for r in e_batches.values())} edges."
    )
