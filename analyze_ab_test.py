import re
import sys
import glob
import ast

def parse_log_line(line):
    # Attempt to extract JSON-like dict from the end of the line
    match = re.search(r"({.*})$", line)
    if match:
        try:
            return ast.literal_eval(match.group(1))
        except:
            return None
    return None

def parse_logs(filepath):
    data = {}
    stats = {
        "funnel": {
            "discovered": 0, # From table
            "http_attempted": 0,
            "http_too_short": 0,
            "headless_eligible": 0,
            "headless_attempted": 0,
            "headless_success": 0
        },
        "skipped_reasons": {},
        "headless_details": {}
    }
    
    in_table = False
    
    with open(filepath, 'r') as f:
        for line in f:
            # Parse Summary Table for Discovery Counts
            if "REPORTE DE SALUD DE FUENTES" in line:
                in_table = True
                continue
            if in_table and "====" in line:
                continue
            if in_table and ("🎉" in line or "Exit code" in line):
                in_table = False
                continue
                
            if in_table:
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 6:
                    source = parts[0]
                    found = int(parts[2]) if parts[2].isdigit() else 0
                    saved = int(parts[3]) if parts[3].isdigit() else 0
                    diagnosis = parts[6] if len(parts) > 6 else ""
                    
                    data[source] = {
                        "saved": saved,
                        "found": found,
                        "diagnosis": diagnosis
                    }

            # Parse Structured Logs
            log_entry = parse_log_line(line)
            if log_entry:
                event = log_entry.get("event", "")
                details = log_entry.get("details", {})
                source_id = log_entry.get("source_id") or details.get("source_id") or "unknown"

                if event == "enrichment.http.result":
                    stats["funnel"]["http_attempted"] += 1
                    length = details.get("length", 0)
                    if length < 500:
                        stats["funnel"]["http_too_short"] += 1
                
                elif event == "enrichment.headless.eligible":
                    stats["funnel"]["headless_eligible"] += 1
                    
                elif event == "enrichment.headless.skipped":
                    reason = details.get("reason", "unknown")
                    stats["skipped_reasons"][reason] = stats["skipped_reasons"].get(reason, 0) + 1
                    
                elif event == "enrichment.router.selected":
                    strategy = details.get("strategy")
                    success = details.get("success")
                    
                    if strategy == "headless":
                        stats["funnel"]["headless_attempted"] += 1
                        if success:
                            stats["funnel"]["headless_success"] += 1
                            if source_id not in stats["headless_details"]:
                                stats["headless_details"][source_id] = {"status": "success"}
                        else:
                            if source_id not in stats["headless_details"]:
                                stats["headless_details"][source_id] = {"status": "failed", "reason": details.get("reason")}

    # Discovery Total
    stats["funnel"]["discovered"] = sum(d["found"] for d in data.values())
    
    return data, stats

def generate_report(baseline_data, headless_data, headless_stats):
    # Calculate Deltas
    publishable_baseline = sum(d['saved'] > 0 for d in baseline_data.values())
    publishable_headless = sum(d['saved'] > 0 for d in headless_data.values())
    discovery_ok = headless_stats["funnel"]["discovered"]
    
    report = f"""# Enrichment Routing Report (A/B Verification)

## Executive Summary

| Metric | Baseline (Headless OFF) | Headless (Headless ON) | Delta |
|--------|-------------------------|------------------------|-------|
| Discovery OK Articles | {sum(d['found'] for d in baseline_data.values())} | {discovery_ok} | - |
| Publishable Sources (>=500 chars) | {publishable_baseline} | {publishable_headless} | **{publishable_headless - publishable_baseline:+.0f}** |

## Headless Trigger Funnel

| Stage | Count | Drop-off |
|-------|-------|----------|
| 1. HTTP Enrichment Attempted | {headless_stats['funnel']['http_attempted']} | - |
| 2. HTTP Result < 500 Chars | {headless_stats['funnel']['http_too_short']} | - |
| 3. Headless Eligible (Config OK) | {headless_stats['funnel']['headless_eligible']} | {headless_stats['funnel']['http_too_short'] - headless_stats['funnel']['headless_eligible']} (Disabled/Filtered) |
| 4. Headless Attempted | {headless_stats['funnel']['headless_attempted']} | {headless_stats['funnel']['headless_eligible'] - headless_stats['funnel']['headless_attempted']} (Budget/Error) |
| 5. Headless Success | {headless_stats['funnel']['headless_success']} | {headless_stats['funnel']['headless_attempted'] - headless_stats['funnel']['headless_success']} (Failed) |

### Skipped Reasons
"""
    if not headless_stats['skipped_reasons']:
        report += "- None\n"
    else:
        for reason, count in headless_stats['skipped_reasons'].items():
            report += f"- **{reason}**: {count}\n"

    report += """
## Improvement Analysis

### Headless Attempts Detail
| Source | Status | Reason |
|--------|--------|--------|
"""
    if not headless_stats['headless_details']:
        report += "| None | - | - |\n"
    else:
        for src, det in headless_stats['headless_details'].items():
            report += f"| {src} | {det['status']} | {det.get('reason', '-')} |\n"

    return report

def main():
    import sys
    baseline_log = "baseline.log"
    headless_log = sys.argv[1] if len(sys.argv) > 1 else "headless.log"
    
    try:
        b_data, _ = parse_logs(baseline_log)
    except:
        b_data = {}
        
    try:
        h_data, h_stats = parse_logs(headless_log)
    except Exception as e:
        print(f"Error parsing headless log {headless_log}: {e}")
        h_data = {}
        h_stats = {
            "funnel": {
                "discovered": 0,
                "http_attempted": 0,
                "http_too_short": 0,
                "headless_eligible": 0,
                "headless_attempted": 0,
                "headless_success": 0
            }, 
            "skipped_reasons": {}, 
            "headless_details": {}
        }
        
    report = generate_report(b_data, h_data, h_stats)
    
    with open("ENRICHMENT_ROUTING_REPORT.md", "w") as f:
        f.write(report)
        
    # Budget Report
    with open("HEADLESS_BUDGET_REPORT.md", "w") as f:
        f.write(f"""# Headless Budget Report

## Stats
- **Eligible**: {h_stats['funnel'].get('headless_eligible', 0)}
- **Attempted**: {h_stats['funnel'].get('headless_attempted', 0)}
- **Budget Skipped**: {h_stats['skipped_reasons'].get('budget_exhausted', 0)}
""")

if __name__ == "__main__":
    main()
