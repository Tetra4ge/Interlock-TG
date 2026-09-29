import json
import logging
from pathlib import Path
from server.store.db import connect
from server.parse.clean import normalize_for_match

logger = logging.getLogger(__name__)

def evaluate_run(run_id: str) -> None:
    """Evaluates extraction run quality and costs."""
    conn = connect()
    
    # 1. Cost metrics
    # A simple estimate from llm_calls table
    cost_rows = conn.execute("SELECT SUM(cost_usd) FROM llm_calls").fetchone()
    total_cost = cost_rows[0] if cost_rows and cost_rows[0] else 0.0
    
    # 2. Status rates (Grounding rejects, Review queue)
    stats = conn.execute("""
        SELECT record_type, status, COUNT(*) 
        FROM records 
        WHERE run_id = ? 
        GROUP BY record_type, status
    """, [run_id]).fetchall()
    
    record_stats = {}
    for rtype, status, count in stats:
        if rtype not in record_stats:
            record_stats[rtype] = {"total": 0, "accepted": 0, "rejected": 0, "review": 0, "fixed": 0}
        record_stats[rtype]["total"] += count
        record_stats[rtype][status] += count
        
    print(f"\n{'='*40}")
    print(f"EVALUATION REPORT: {run_id}")
    print(f"{'='*40}")
    print(f"Total LLM Spend (all time): ${total_cost:.4f}")
    print("\nRecord Pipeline Rates:")
    
    for rtype, data in record_stats.items():
        total = data["total"]
        if total > 0:
            rej_rate = data["rejected"] / total * 100
            rev_rate = data["review"] / total * 100
            acc_rate = data["accepted"] / total * 100
            print(f"  [{rtype.upper()}] {total} total records extracted")
            print(f"    - Accepted (Auto):  {acc_rate:.1f}%")
            print(f"    - Grounding Reject: {rej_rate:.1f}%")
            print(f"    - Review Queue:     {rev_rate:.1f}%")
            
    # 3. F1 / Precision / Recall against Labeled Pages
    print("\nLabeled Page Evaluation:")
    fixtures_dir = Path("tests/fixtures/labeled_pages")
    if not fixtures_dir.exists():
        print("  No labeled pages found.")
    else:
        for fixture in fixtures_dir.glob("*.json"):
            print(f"  Found fixture: {fixture.name}")
            # Placeholder for exact matching logic
            # To compute F1, we would fetch records for this doc_id and page_no
            # and compare extracted fields to expected fields via string matching
            
    conn.close()
    print("\nNext step: Update docs/pilot-report.md with these metrics.")
