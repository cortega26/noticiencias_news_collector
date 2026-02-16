import re
import sys
from collections import defaultdict

def analyze_logs(log_file):
    # Stats: Source -> { "discovered": 0, "enriched_success": 0, "enriched_failed": 0 }
    stats = defaultdict(lambda: {"discovered": 0, "enriched_success": 0, "enriched_failed": 0})
    
    # Target journals
    TARGETS = {"nature", "science", "nejm"}
    
    current_session = None
    
    print(f"Analyzing {log_file}...")
    
    with open(log_file, 'r') as f:
        # Read all lines to find the last session
        lines = f.readlines()
        
    # Find start of last session
    start_idx = 0
    for i, line in enumerate(lines):
        if "NEWS COLLECTOR SYSTEM INICIADO" in line:
            start_idx = i
            
    print(f"Analyzing session starting at line {start_idx}")
    
    for line in lines[start_idx:]:
        if not current_session:
            # Try finding session_id in any line
            match_sess = re.search(r"'session_id': '([^']+)'", line)
            if match_sess:
                current_session = match_sess.group(1)
        
        if "News Collector System (ID:" in line:
             current_session = line.split("ID: ")[1].strip().replace(")", "")
        
        
        # We look for "collector.source.completed" which has the summary stats
        if "collector.source.completed" in line:
            # Extract Source
            # format: ... 'source_id': 'nature', ... 'details': {'articles_found': 5, 'articles_saved': 5, ...}}
            match_source = re.search(r"'source_id': '([^']+)'", line)
            if match_source:
                source = match_source.group(1)
                if source in TARGETS:
                    # Extract Details
                    match_found = re.search(r"'articles_found': (\d+)", line)
                    match_saved = re.search(r"'articles_saved': (\d+)", line)
                    
                    found = int(match_found.group(1)) if match_found else 0
                    saved = int(match_saved.group(1)) if match_saved else 0
                    
                    # Saved = Enriched Success (in this context, as they passed Stage B)
                    stats[source]["enriched_success"] += saved
                    
                    # Failed = Found - Saved (approx, includes all drop reasons but good enough)
                    stats[source]["enriched_failed"] += (found - saved)

    # Generate Markdown Report
    print("\n# Journal Enrichment Report")
    print(f"**Session**: {current_session}\n")
    print("| Journal | Discovered (Approx) | Publishable (Enriched) | Failed Enrichment | Success Rate |")
    print("| :--- | :---: | :---: | :---: | :---: |")
    
    report_content = "# Journal Enrichment Report\n\n"
    report_content += f"**Session**: {current_session}\n\n"
    report_content += "| Journal | Discovered (Approx) | Publishable (Enriched) | Failed Enrichment | Success Rate |\n"
    report_content += "| :--- | :---: | :---: | :---: | :---: |\n"
    
    for source in sorted(TARGETS):
        s = stats[source]
        # Discovered is at least success + failed. 
        discovered = s["enriched_success"] + s["enriched_failed"]
        rate = (s["enriched_success"] / discovered * 100) if discovered > 0 else 0
        row = f"| `{source}` | {discovered} | **{s['enriched_success']}** | {s['enriched_failed']} | {rate:.1f}% |"
        print(row)
        report_content += row + "\n"

    with open("JOURNAL_ENRICHMENT_REPORT.md", "w") as f:
        f.write(report_content)
    print("\nReport saved to JOURNAL_ENRICHMENT_REPORT.md")

if __name__ == "__main__":
    analyze_logs("data/logs/collector.log")
