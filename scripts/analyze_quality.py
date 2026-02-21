import ast
import json
import re
from collections import defaultdict

LOG_FILE = "data/logs/collector.log"


def analyze_logs():
    print(f"Analyzing {LOG_FILE}...")

    source_stats = defaultdict(
        lambda: {
            "found": 0,
            "saved": 0,
            "stage_b_failures": 0,
            "errors": [],
            "status": "UNKNOWN",
        }
    )

    try:
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print("Log file not found.")
        return

    # Scan backwards to find the last run start
    start_index = 0
    for i in range(len(lines) - 1, -1, -1):
        if "NEWS COLLECTOR SYSTEM INICIADO" in lines[i]:
            start_index = i
            break

    print(f"Analyzing run starting at line {start_index}...")
    current_lines = lines[start_index:]

    for line in current_lines:
        msg = ""
        try:
            # Handle JSON logs or plain logs
            if line.startswith("{"):
                log_entry = json.loads(line)
                msg_obj = log_entry.get("record", {}).get("message", "")
                if isinstance(msg_obj, str):
                    msg = msg_obj
                else:
                    msg = str(msg_obj)
            else:
                # Clean loguru prefix if needed
                parts = line.split("|")
                if len(parts) > 3:
                    msg = parts[-1].strip()
                else:
                    msg = line

        except Exception:
            msg = line

        # Parse Dictionary-like messages
        match = re.search(r"\{.*\}", msg)
        if match:
            try:
                dict_str = match.group(0)
                data = ast.literal_eval(dict_str)
                event = data.get("event")
                sid = data.get("source_id")
                details = data.get("details", {})

                if sid:
                    if (
                        event == "collector.source.completed"
                        or event == "collector.source.failed"
                    ):
                        source_stats[sid]["found"] = details.get("articles_found", 0)
                        source_stats[sid]["saved"] = details.get("articles_saved", 0)
                        err = data.get("error_message") or details.get("error_message")
                        if err:
                            source_stats[sid]["errors"].append(err)

                        if "failed" in str(event):
                            source_stats[sid]["status"] = "FAIL"
                        else:
                            source_stats[sid]["status"] = "OK"

                    elif event == "collector.contract.stage_b_failed":
                        source_stats[sid]["stage_b_failures"] += 1

            except Exception:
                pass

    # Generate Report
    print("\nQUALITY CONTRACT REPORT")
    print("=" * 100)
    print(
        f"{'Source':<25} | {'Disc. (Found)':<15} | {'Saved (DB)':<12} | {'Stage B Fail':<12} | {'Publishable':<12} | {'Note'}"
    )
    print("-" * 100)

    total_sources = 0
    discovery_ok = 0
    enrichment_ok = 0  # Not tracked directly here, assuming fetch didn't fail -> saved
    publishable_ok = 0
    blocked_count = 0

    for sid, stats in sorted(source_stats.items(), key=lambda x: x[0]):
        total_sources += 1
        found = stats["found"]
        saved = stats["saved"]  # Includes candidates
        stage_b_fail = stats["stage_b_failures"]
        publishable = max(0, saved - stage_b_fail)

        note = ""
        if stats["status"] == "FAIL":
            note = "BLOCKED/ERROR"
            blocked_count += 1
            if stats["errors"]:
                note += f" ({str(stats['errors'][0])[:20]})"
        elif saved == 0 and found > 0:
            note = "Filtered (Dedup?)"
        elif saved > 0 and publishable == 0:
            note = "Discovery Only (Too Short)"
        elif publishable > 0:
            note = "Publishable"

        if saved > 0:
            discovery_ok += 1

        if publishable > 0:
            publishable_ok += 1

        print(
            f"{sid:<25} | {found:<15} | {saved:<12} | {stage_b_fail:<12} | {publishable:<12} | {note}"
        )

    print("-" * 100)
    print(f"Total Sources:       {total_sources}")
    print(f"Discovery OK:        {discovery_ok} (Saved as Candidate)")
    print(f"Publishable:         {publishable_ok} (Met 500 char limit)")
    print(f"Blocked/Error:       {blocked_count}")
    print("=" * 100)


if __name__ == "__main__":
    analyze_logs()
