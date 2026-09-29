import os
import glob
import hashlib
import json
import logging
from server.graph.client import get_tg_connection

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
    with open("server/graph/gsql/schema.gsql", "r") as f:
        schema = f.read()
        
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
        with open(lock_file, "r") as f:
            locks = json.load(f)
            
    changed = False
    new_locks = {}
    
    for qf in query_files:
        with open(qf, "r") as f:
            content = f.read()
            
        h = hashlib.sha256(content.encode()).hexdigest()
        new_locks[qf] = h
        if locks.get(qf) != h:
            changed = True
            
    if not changed:
        logger.info("No queries changed, skipping installation.")
        return
        
    logger.info("Queries changed, installing (this takes a few minutes compiling C++)...")
    combined = ""
    for qf in query_files:
        with open(qf, "r") as f:
            combined += f.read() + "\n"
            
    combined += "INSTALL QUERY ALL\n"
    out = conn.gsql(combined)
    logger.info(f"Queries installed: {out}")
    
    with open(lock_file, "w") as f:
        json.dump(new_locks, f)
        
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    apply_schema()
    install_queries()
