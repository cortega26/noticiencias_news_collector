import json
import os
import sqlite3

DB_PATH = "data/metrics/production/enrichment_metrics.db"

if not os.path.exists(DB_PATH):
    print(json.dumps({"error": f"DB not found at {DB_PATH}"}))
    exit(0)

try:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM enrichment_metrics")
    rows = cursor.fetchall()
    metrics = [dict(row) for row in rows]

    cursor.execute(
        "SELECT source_id, strategy, event_type, metadata, timestamp FROM enrichment_history ORDER BY id DESC LIMIT 10"
    )
    rows_fail = cursor.fetchall()
    failures = []
    for r in rows_fail:
        d = dict(r)
        if d["metadata"]:
            try:
                d["metadata"] = json.loads(d["metadata"])
            except:
                pass
        failures.append(d)

    print("--- METRICS ---")
    print(json.dumps(metrics, indent=2))
    print("--- HISTORY ---")
    print(json.dumps(failures, indent=2))

except Exception as e:
    print(f"Error: {e}")
