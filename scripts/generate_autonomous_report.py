
import sqlite3
import pandas as pd
import os
import yaml
from pathlib import Path

DB_PATH = os.getenv("METRICS_DB_PATH", "data/metrics/production/enrichment_metrics.db")
LOCKS_PATH = "config/strategy_locks.yaml"
REPORT_PATH = "PRODUCTION_AUTONOMOUS_OPERATION_REPORT.md"

def main():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    
    # 1. Enrichment Metrics
    try:
        df = pd.read_sql_query("SELECT * FROM enrichment_metrics", conn)
    except Exception as e:
        print(f"Error reading metrics: {e}")
        return
        
    # Calculate derived metrics
    df["yield_pct"] = (df["total_publishable"] / df["total_enrichment_attempted"] * 100).fillna(0).round(1)
    df["headless_rate"] = (df["headless_success"] / df["headless_attempts"] * 100).fillna(0).round(1)
    df["proxy_rate"] = (df["proxy_success"] / df["proxy_attempts"] * 100).fillna(0).round(1)
    
    # 2. Strategy Locks
    locks = {}
    if os.path.exists(LOCKS_PATH):
        with open(LOCKS_PATH, "r") as f:
            data = yaml.safe_load(f)
            locks = data.get("locks", {})

    with open(REPORT_PATH, "w") as f:
        f.write("# Production Autonomous Operation Report\n\n")
        f.write("**Status:** Continuous Operation Active\n")
        f.write(f"**Active Sources:** {len(df)}\n")
        f.write(f"**Strategy Locks Applied:** {len(locks)}\n\n")
        
        f.write("## 1. Strategy Locks (Automated)\n\n")
        if locks:
            f.write("| Source | Strategy | Rationale | Created At |\n")
            f.write("|---|---|---|---|\n")
            for source, lock in locks.items():
                f.write(f"| {source} | **{lock.get('strategy')}** | {lock.get('rationale')} | {lock.get('created_at')} |\n")
        else:
            f.write("No strategy locks applied yet.\n")
        f.write("\n")
        
        f.write("## 2. Source Performance (Yield & Strategy)\n\n")
        cols = ["source_id", "total_enrichment_attempted", "yield_pct", "headless_rate", "proxy_rate", "avg_enrichment_time"]
        
        # Sort by Yield DESC
        f.write(df[cols].sort_values("yield_pct", ascending=False).to_markdown(index=False) if hasattr(df, "to_markdown") and False else df[cols].sort_values("yield_pct", ascending=False).to_string(index=False))
        f.write("\n\n")
        
        f.write("## 3. Resource Usage\n\n")
        total_proxy = df["proxy_requests_used"].sum()
        total_headless = df["headless_seconds_used"].sum()
        f.write(f"- **Total Proxy Requests:** {total_proxy}\n")
        f.write(f"- **Total Headless Seconds:** {total_headless:.2f}s\n\n")
        
        f.write("## 4. Top Failure Reasons\n\n")
        try:
            # Parse failures from history
            fail_df = pd.read_sql_query("SELECT strategy, metadata FROM enrichment_history WHERE event_type='failure'", conn)
            if not fail_df.empty:
                # Extract reason from metadata JSON
                import json
                fail_df["reason"] = fail_df["metadata"].apply(lambda x: json.loads(x).get("reason", "unknown"))
                
                # Group by Strategy + Reason
                summary = fail_df.groupby(["strategy", "reason"]).size().reset_index(name="count")
                summary = summary.sort_values("count", ascending=False).head(10)
                
                f.write(summary.to_markdown(index=False) if hasattr(summary, "to_markdown") and False else summary.to_string(index=False))
            else:
                f.write("No recorded failures.")
        except Exception as e:
            f.write(f"Error parsing failure history: {e}")
        f.write("\n")

    print(f"Report generated at {REPORT_PATH}")

if __name__ == "__main__":
    main()
