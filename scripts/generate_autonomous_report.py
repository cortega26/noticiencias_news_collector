import json
import os
import sqlite3

import yaml

DB_PATH = os.getenv("METRICS_DB_PATH", "data/metrics/production/enrichment_metrics.db")
LOCKS_PATH = "config/strategy_locks.yaml"
REPORT_PATH = "PRODUCTION_AUTONOMOUS_OPERATION_REPORT.md"


def main():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1. Enrichment Metrics
    try:
        cur.execute("SELECT * FROM enrichment_metrics")
        rows = cur.fetchall()
    except Exception as e:
        print(f"Error reading metrics: {e}")
        return

    # Process metrics
    metrics = []
    for row in rows:
        d = dict(row)
        total_attempt = d.get("total_enrichment_attempted") or 0
        total_pub = d.get("total_publishable") or 0
        h_succ = d.get("headless_success") or 0
        h_att = d.get("headless_attempts") or 0
        p_succ = d.get("proxy_success") or 0
        p_att = d.get("proxy_attempts") or 0

        yield_pct = round(total_pub / total_attempt * 100, 1) if total_attempt else 0.0
        h_rate = round(h_succ / h_att * 100, 1) if h_att else 0.0
        p_rate = round(p_succ / p_att * 100, 1) if p_att else 0.0

        d["yield_pct"] = yield_pct
        d["headless_rate"] = h_rate
        d["proxy_rate"] = p_rate
        metrics.append(d)

    # Sort by yield DESC
    metrics.sort(key=lambda x: x["yield_pct"], reverse=True)

    # 2. Strategy Locks
    locks = {}
    if os.path.exists(LOCKS_PATH):
        with open(LOCKS_PATH, "r") as f:
            data = yaml.safe_load(f) or {}
            locks = data.get("locks", {})

    with open(REPORT_PATH, "w") as f:
        f.write("# Production Autonomous Operation Report\n\n")
        f.write("**Status:** Continuous Operation Active\n")
        f.write(f"**Active Sources:** {len(metrics)}\n")
        f.write(f"**Strategy Locks Applied:** {len(locks)}\n\n")

        f.write("## 1. Strategy Locks (Automated)\n\n")
        if locks:
            f.write("| Source | Strategy | Rationale | Created At |\n")
            f.write("|---|---|---|---|\n")
            for source, lock in locks.items():
                f.write(
                    f"| {source} | **{lock.get('strategy')}** | {lock.get('rationale')} | {lock.get('created_at')} |\n"
                )
        else:
            f.write("No strategy locks applied yet.\n")
        f.write("\n")

        f.write("## 2. Source Performance (Yield & Strategy)\n\n")
        f.write(
            "| source_id | total_enrichment_attempted | yield_pct | headless_rate | proxy_rate | avg_enrichment_time |\n"
        )
        f.write("|---|---|---|---|---|---|\n")
        for m in metrics:
            f.write(
                f"| {m.get('source_id')} | {m.get('total_enrichment_attempted')} | {m.get('yield_pct')} | {m.get('headless_rate')} | {m.get('proxy_rate')} | {m.get('avg_enrichment_time')} |\n"
            )
        f.write("\n\n")

        f.write("## 3. Resource Usage\n\n")
        total_proxy = sum((m.get("proxy_requests_used") or 0) for m in metrics)
        total_headless = sum((m.get("headless_seconds_used") or 0.0) for m in metrics)
        f.write(f"- **Total Proxy Requests:** {total_proxy}\n")
        f.write(f"- **Total Headless Seconds:** {total_headless:.2f}s\n\n")

        f.write("## 4. Top Failure Reasons\n\n")
        try:
            # Parse failures from history
            cur.execute(
                "SELECT strategy, metadata FROM enrichment_history WHERE event_type='failure'"
            )
            fails = cur.fetchall()

            if fails:
                summary = {}
                for fail in fails:
                    strat = fail["strategy"]
                    meta_str = fail["metadata"]
                    try:
                        meta = json.loads(meta_str)
                        reason = meta.get("reason", "unknown")
                    except Exception:
                        reason = "unknown"
                    key = (strat, reason)
                    summary[key] = summary.get(key, 0) + 1

                # Sort descending
                sorted_summary = sorted(
                    summary.items(), key=lambda x: x[1], reverse=True
                )[:10]

                f.write("| strategy | reason | count |\n")
                f.write("|---|---|---|\n")
                for (strat, reason), count in sorted_summary:
                    f.write(f"| {strat} | {reason} | {count} |\n")
            else:
                f.write("No recorded failures.")
        except Exception as e:
            f.write(f"Error parsing failure history: {e}")
        f.write("\n")

    print(f"Report generated at {REPORT_PATH}")


if __name__ == "__main__":
    main()
