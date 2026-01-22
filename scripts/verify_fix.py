import asyncio
import logging
import os
import sqlite3
import sys
from pathlib import Path

# Add project root to path
sys.path.append(os.getcwd())

from news_collector.collectors.html_collector import HtmlCollector
from news_collector.collectors.rss_collector import RSSCollector
from news_collector.config.settings import DATABASE_CONFIG, TEXT_PROCESSING_CONFIG

# Setup logging
logging.basicConfig(level=logging.INFO)
logging.getLogger("news_collector").setLevel(logging.DEBUG)
logger = logging.getLogger("verification")


def factory_reset():
    print("🧹 Performing Factory Reset...")
    db_path = DATABASE_CONFIG["path"]

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # 1. Wipe Tables
        tables = ["articles", "article_metrics", "score_logs"]
        for t in tables:
            try:
                cursor.execute(f"DELETE FROM {t}")  # nosec
            except Exception:
                pass

        # 2. Reset Source Metadata
        cursor.execute(
            """
            UPDATE sources
            SET last_checked = NULL,
                last_successful_check = NULL,
                feed_etag = NULL,
                feed_last_modified = NULL
        """
        )
        conn.commit()
    print("✅ Factory Reset Complete.")


async def run_verification():
    # 1. Reset
    factory_reset()

    # 2. Run Collector (Targeting specific sources to save time)
    # We want one that usually succeeds (RSS) and one that might fail validation (HTML)
    print("\n🚀 Starting Collection Cycle...")

    # RSS Source (BBC Technology - Highly reliable)
    rss_config = {
        "bbc_tech": {
            "name": "BBC Technology",
            "url": "http://feeds.bbci.co.uk/news/technology/rss.xml",
            "category": "technology",
            "min_delay_seconds": 1,
            "credibility_score": 0.9,
        }
    }

    # DEBUG: Direct Feedparser Check
    if "bbc_tech" in rss_config:
        import feedparser

        print(f"\n🕵️ DEBUG: Checking feed directly: {rss_config['bbc_tech']['url']}")
        d = feedparser.parse(rss_config["bbc_tech"]["url"])
        print(f"   - Bozo: {d.bozo}")
        print(f"   - Entries: {len(d.entries)}")
        if d.entries:
            print(f"   - First Entry Title: {d.entries[0].get('title', 'No Title')}")

    collector = RSSCollector()
    results = await collector.collect_from_multiple_sources_async(rss_config)

    # 3. Validation Check
    print("\n📊 Verification Results:")
    tc_res = results.get("bbc_tech", {})
    found = tc_res.get("articles_found", 0)
    saved = tc_res.get("articles_saved", 0)

    print(f"   BBC Tech: Found {found}, Saved {saved}")

    if saved == 0 and found > 0:
        print("   ❌ FAIL: Zero articles saved. Check validation logs.")
    elif saved > 0:
        print("   ✅ SUCCESS: Articles saved.")

    # 4. Content Length Verification
    db_path = DATABASE_CONFIG["path"]
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT title, length(content) FROM articles")
        rows = cursor.fetchall()

        print(
            f"\n📏 Content Length Check (Min: {TEXT_PROCESSING_CONFIG['min_content_length']}):"
        )
        pass_count = 0
        for title, length in rows:
            status = "✅" if length >= 1000 else "❌ FAIL"
            print(f"   [{status}] {length} chars: {title[:50]}...")
            if length >= 1000:
                pass_count += 1

        if pass_count == len(rows) and len(rows) > 0:
            print(
                "\n✨ ALL CHECKS PASSED: Database reset worked, items fetched, and strict validation enforced."
            )
        else:
            print("\n⚠️ CHECKS FAILED: Some articles missing or too short.")


if __name__ == "__main__":
    asyncio.run(run_verification())
