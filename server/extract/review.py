import json
import sys
from server.store.db import connect

def review_cli() -> None:
    """A simple CLI interface for processing the manual review queue."""
    conn = connect()
    
    # Fetch pending review items
    items = conn.execute("""
        SELECT r.record_id, r.doc_id, r.record_type, r.payload_json, rq.reason, rq.created_at
        FROM records r
        JOIN review_queue rq ON r.record_id = rq.record_id
        WHERE r.status = 'review' AND rq.decision IS NULL
        ORDER BY rq.created_at ASC
    """).fetchall()
    
    if not items:
        print("No items in the review queue! 🎉")
        conn.close()
        return
        
    print(f"Found {len(items)} items in the review queue.\n")
    
    for item in items:
        record_id, doc_id, record_type, payload_json, reason, created_at = item
        payload = json.loads(payload_json)
        
        print("-" * 60)
        print(f"Doc: {doc_id} | Type: {record_type} | Reason: {reason}")
        
        # Highlight evidence quote if present
        evidence = payload.get("evidence", {})
        quote = evidence.get("quote", "NOT FOUND")
        page = evidence.get("page", "NOT FOUND")
        print(f"Evidence [Page {page}]: {quote}")
        print("-" * 20)
        
        print("Record Data:")
        print(json.dumps(payload, indent=2))
        print("-" * 60)
        
        while True:
            choice = input("[A]ccept  [R]eject  [E]dit JSON  [S]kip  [Q]uit: ").strip().lower()
            if choice == 'q':
                print("Exiting review tool.")
                conn.close()
                sys.exit(0)
            elif choice == 's':
                print("Skipped.\n")
                break
            elif choice == 'a':
                conn.execute("UPDATE records SET status = 'accepted' WHERE record_id = ?", [record_id])
                conn.execute("UPDATE review_queue SET decision = 'accepted', reviewed_at = datetime('now') WHERE record_id = ?", [record_id])
                conn.commit()
                print("Accepted.\n")
                break
            elif choice == 'r':
                conn.execute("UPDATE records SET status = 'rejected' WHERE record_id = ?", [record_id])
                conn.execute("UPDATE review_queue SET decision = 'rejected', reviewed_at = datetime('now') WHERE record_id = ?", [record_id])
                conn.commit()
                print("Rejected.\n")
                break
            elif choice == 'e':
                print("Enter new JSON (single line), or press enter to cancel:")
                new_json = input("> ").strip()
                if new_json:
                    try:
                        # validate it's valid json
                        json.loads(new_json)
                        conn.execute("UPDATE records SET payload_json = ?, status = 'fixed' WHERE record_id = ?", [new_json, record_id])
                        conn.execute("UPDATE review_queue SET decision = 'fixed', reviewed_at = datetime('now') WHERE record_id = ?", [record_id])
                        conn.commit()
                        print("Fixed and saved.\n")
                        break
                    except Exception as e:
                        print(f"Invalid JSON: {e}")
                else:
                    print("Edit cancelled.")
            else:
                print("Invalid choice. Please press A, R, E, S, or Q.")
                
    print("Review queue empty. Good job!")
    conn.close()
