#!/usr/bin/env python3
"""
Feed Diagnostics Tool for Noticiencias News Collector
=====================================================

This script validates the health of all configured RSS feeds.
It performs:
1. DNS/Connectivity check
2. Feed Fetching & Latency measurement
3. Content & Schema validation
4. Failure classification

Output:
- Console report with icons/status
- JSON report for programmatic use
"""

import sys
import time
import json
import logging
import requests
import feedparser
from urllib.parse import urlparse
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add project root to path to import config
from pathlib import Path
project_root = Path(__file__).resolve().parents[1]
sys.path.append(str(project_root))

try:
    from news_collector.config.sources import ALL_SOURCES
except ImportError:
    print("Error: Could not import ALL_SOURCES. Run this script from the project root or ensure python path is correct.")
    sys.exit(1)

# Configure Logging
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("FeedDiagnostics")

@dataclass
class FeedStatus:
    source_id: str
    name: str
    url: str
    status: str  # "OK", "DEGRADED", "FAIL"
    latency_ms: float
    status_code: Optional[int]
    articles_found: int
    error_category: Optional[str] # "NETWORK", "AUTH", "TIMEOUT", "SCHEMA", "EMPTY", "PARSE"
    error_message: Optional[str]
    last_checked: str

class FeedDiagnoser:
    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self.headers = {
            "User-Agent": "NoticienciasBot/1.0 (+https://noticiencias.com)",
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
            "Cache-Control": "no-cache"
        }

    def classify_error(self, exc: Exception) -> str:
        msg = str(exc).lower()
        if "timeout" in msg:
            return "TIMEOUT"
        if "connection" in msg or "dns" in msg or "resolve" in msg:
            return "NETWORK"
        if "ssl" in msg or "certificate" in msg:
            return "SSL/Security"
        return "UNKNOWN"

    def check_feed(self, source_id: str, config: Dict[str, Any]) -> FeedStatus:
        url = config["url"]
        start_time = time.time()
        
        status = FeedStatus(
            source_id=source_id,
            name=config["name"],
            url=url,
            status="FAIL",
            latency_ms=0.0,
            status_code=None,
            articles_found=0,
            error_category=None,
            error_message=None,
            last_checked=time.strftime("%Y-%m-%d %H:%M:%S")
        )

        try:
            # 1. Connectivity & Fetch
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            status.latency_ms = (time.time() - start_time) * 1000
            status.status_code = response.status_code

            if response.status_code >= 400:
                status.status = "FAIL"
                if response.status_code in [401, 403]:
                    status.error_category = "AUTH"
                elif response.status_code == 429:
                    status.error_category = "RATE_LIMIT"
                elif response.status_code >= 500:
                    status.error_category = "SERVER"
                else:
                    status.error_category = "HTTP_ERROR"
                status.error_message = f"HTTP {response.status_code}"
                return status

            # 2. Parsing & Validation
            content = response.content
            if not content:
                status.status = "FAIL"
                status.error_category = "EMPTY"
                status.error_message = "Empty response body"
                return status

            parsed = feedparser.parse(content)
            
            # Check for bozo (parse errors)
            if parsed.bozo:
                # Some bozo errors are acceptable, others are fatal.
                # If we have entries, we might consider it DEGRADED instead of FAIL
                if not parsed.entries:
                    status.status = "FAIL"
                    status.error_category = "PARSE"
                    status.error_message = str(parsed.bozo_exception)
                    return status
                else:
                     status.status = "DEGRADED" # Has entries but malformed
            
            entries_count = len(parsed.entries)
            status.articles_found = entries_count
            
            if entries_count == 0:
                status.status = "DEGRADED" # Technically valid but empty feed
                status.error_category = "NO_CONTENT"
                status.error_message = "No entries found in feed"
            else:
                # 3. Schema Validation on first entry
                first_entry = parsed.entries[0]
                missing_fields = []
                if not hasattr(first_entry, "title"): missing_fields.append("title")
                if not hasattr(first_entry, "link"): missing_fields.append("link")
                
                # Check summary/description/content
                has_content = any(hasattr(first_entry, f) for f in ["summary", "description", "content", "content:encoded"])
                if not has_content: missing_fields.append("summary/content")

                if missing_fields:
                    status.status = "DEGRADED"
                    status.error_category = "SCHEMA"
                    status.error_message = f"Missing fields: {', '.join(missing_fields)}"
                elif status.status != "DEGRADED": # Don't overwrite if already degraded
                    status.status = "OK"

        except Exception as e:
            status.latency_ms = (time.time() - start_time) * 1000
            status.status = "FAIL"
            status.error_category = self.classify_error(e)
            status.error_message = str(e)

        return status

def main():
    print(f"🔍 Diagnosing {len(ALL_SOURCES)} feeds...")
    print("-" * 60)
    print(f"{'ID':<20} | {'Status':<10} | {'Latency':<8} | {'Items':<5} | {'Info'}")
    print("-" * 60)

    results = []
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_source = {
            executor.submit(FeedDiagnoser().check_feed, sid, conf): sid 
            for sid, conf in ALL_SOURCES.items()
        }

        for future in as_completed(future_to_source):
            try:
                res = future.result()
                results.append(asdict(res))
                
                # Console Output
                status_icon = "✅" if res.status == "OK" else "⚠️" if res.status == "DEGRADED" else "❌"
                info = res.error_message if res.error_message else ""
                
                # Truncate ID for display
                print(f"{res.source_id[:20]:<20} | {status_icon} {res.status:<7} | {int(res.latency_ms):>4}ms | {res.articles_found:>5} | {info}")
                
            except Exception as exc:
                print(f"Error processing future: {exc}")

    # Summary
    pass_count = sum(1 for r in results if r['status'] == 'OK')
    degraded_count = sum(1 for r in results if r['status'] == 'DEGRADED')
    fail_count = sum(1 for r in results if r['status'] == 'FAIL')

    print("-" * 60)
    print(f"Summary: {pass_count} OK, {degraded_count} Degraded, {fail_count} Failed")
    
    # Save Report
    output_path = "feed_health_report.json"
    with open(output_path, "w") as f:
        json.dump({
            "timestamp": time.time(),
            "summary": {
                "total": len(results),
                "ok": pass_count,
                "degraded": degraded_count,
                "failed": fail_count
            },
            "feeds": results
        }, f, indent=2)
    print(f"📄 Detailed report saved to {output_path}")

if __name__ == "__main__":
    main()
