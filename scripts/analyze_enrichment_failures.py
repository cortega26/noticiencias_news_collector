
import json
import re
import sys
import ast
from collections import defaultdict

LOG_FILE = "data/logs/collector.log"
OUTPUT_FILE = "ENRICHMENT_FAILURE_REPORT.md"

def analyze_failures():
    print(f"Analyzing {LOG_FILE}...")
    
    # Data structures
    sessions = defaultdict(lambda: {"source_failures": defaultdict(list), "url_errors": {}, "timestamp": 0})
    
    try:
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print("Log file not found.")
        return
            
    print(f"Scanning {len(lines)} lines...")
    
    # Pass 1: Collect Errors and Failures by Session
    for line in lines:
        msg = ""
        try:
            if line.startswith("{"):
                log_entry = json.loads(line)
                msg_obj = log_entry.get("record", {}).get("message", "")
                msg = str(msg_obj)
                ts = log_entry.get("record", {}).get("time", {}).get("timestamp", 0)
            else:
                 parts = line.split("|")
                 if len(parts) > 3:
                     msg = parts[-1].strip()
                 else:
                     msg = line
                 ts = 0 # Todo parse if needed, but JSON is main source
        except:
            msg = line
            ts = 0

        # Extract Dict data
        match = re.search(r"\{.*\}", msg)
        if match:
            try:
                dict_str = match.group(0)
                data = ast.literal_eval(dict_str)
                event = data.get("event")
                sid = data.get("source_id")
                session_id = data.get("session_id", "unknown_session")
                details = data.get("details", {})
                
                # Update session timestamp
                if ts > sessions[session_id]["timestamp"]:
                    sessions[session_id]["timestamp"] = ts
                
                # Capture Fetch Errors
                if event == "collector.article.fetch_error":
                    url = details.get("url")
                    error = details.get("error") or data.get("error_message")
                    status = details.get("status_code")
                    if url:
                        sessions[session_id]["url_errors"][url] = {"error": error, "status": status}
                
                # Capture Stage B Failures (Enrichment/Quality)
                elif event == "collector.contract.stage_b_failed":
                    if sid:
                        sessions[session_id]["source_failures"][sid].append({
                            "url": details.get("url"),
                            "len": details.get("len"),
                            "reason": details.get("reason"),
                            "threshold": details.get("threshold")
                        })
                        
            except Exception as e:
                pass

    # Find Best Session (Most failures or Latest with failures)
    best_session_id = None
    max_failures = 0
    latest_ts = 0
    
    for sess_id, data in sessions.items():
        count = sum(len(f) for f in data["source_failures"].values())
        if count > 0:
            # We prefer the LATEST session that has failures
            if data["timestamp"] > latest_ts:
                latest_ts = data["timestamp"]
                best_session_id = sess_id
                max_failures = count
    
    if not best_session_id:
        print("No sessions with Stage B failures found.")
        return

    print(f"Selected Session: {best_session_id} (Failures: {max_failures})")
    target_session = sessions[best_session_id]
    source_failures = target_session["source_failures"]
    url_errors = target_session["url_errors"]

    # Pass 2: Generate Report
    with open(OUTPUT_FILE, "w") as out:
        out.write(f"# Enrichment Failure Report (Session: {best_session_id})\n\n")
        out.write("This report details sources that were successfully discovered (Stage A) but failed the enrichment quality check (Stage B).\n\n")
        out.write("| Source | Failure Type | Recommended Mode | Details |\n")
        out.write("| :--- | :--- | :--- | :--- |\n")
        
        # Priority sort order
        def get_priority(item):
            sid, failures = item
            
            # Analyze first failure to determine likely mode
            unique_failures = {}
            for f in failures:
                unique_failures[f['url']] = f
            if not unique_failures: return 99
            
            sample = list(unique_failures.values())[0]
            url = sample['url']
            length = sample['len']
            
            fetch_err = url_errors.get(url, {})
            status = fetch_err.get("status")
            
            # Logic duplicated for sorting (simplified)
            if status == 403: return 1 # Headless
            if 0 < length < 500: return 1 # Headless (likely JS)
            if sid in ["nature", "science", "nejm"]: return 3 # Impossible
            
            return 2 # Others
            
        for sid, failures in sorted(source_failures.items(), key=get_priority):
            # Aggregate stats for this source
            unique_failures = {} # dedupe by URL
            for f in failures:
                unique_failures[f['url']] = f
            
            if not unique_failures:
                continue

            # Analyze the first failure as a sample
            sample = list(unique_failures.values())[0]
            url = sample['url']
            length = sample['len']
            
            # Check for known fetch errors for this URL
            fetch_err = url_errors.get(url, {})
            status = fetch_err.get("status")
            err_msg = fetch_err.get("error")
            
            failure_type = "Content Too Short"
            rec_mode = "headless" # Default assumption: JS needed
            
            if status == 403:
                failure_type = "HTTP 403 Forbidden"
                rec_mode = "headless"
            elif status == 401:
                failure_type = "HTTP 401 Unauthorized"
                rec_mode = "impossible" # Likely paywall
            elif status == 429:
                failure_type = "HTTP 429 Rate Limit" 
                rec_mode = "http (adjust rate)"
            elif err_msg and "timeout" in str(err_msg).lower():
                failure_type = "Timeout"
                rec_mode = "http (retry)"
            elif 0 < length < 100:
                failure_type = f"Empty/Stub ({length} chars)"
                rec_mode = "headless"
            
            # Known hard cases override
            if sid in ["nature", "science", "nejm"]:
                failure_type = "Paywall/Bot-Protection"
                rec_mode = "impossible (or headless+auth)"
            elif sid in ["deepmind_blog", "openai_blog"]:
                 # These are usually statically generate, maybe just RSS summary only?
                 # If RSSCollector failed to extract full text, it means 
                 # BaseCollector.fetch_html returned something but extracting content failed.
                 # DeepMind/OpenAI blogs usually behave well with Headless.
                 failure_type = f"Content Too Short ({length} chars)"
                 rec_mode = "headless"

            
            details = f"HTTP {status or '200'} <br> Len: {length} <br> [Example]({url})"
            
            out.write(f"| `{sid}` | {failure_type} | **{rec_mode}** | {details} |\n")

    print(f"Report generated: {OUTPUT_FILE}")

if __name__ == "__main__":
    analyze_failures()
