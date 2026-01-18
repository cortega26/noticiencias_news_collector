
import asyncio
import logging
import sys
from typing import Any, Dict

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("live_check")

# Monkeypatch DB saving to avoid writing to DB
from news_collector.collectors.base_collector import BaseCollector

# _save_article is synchronous in BaseCollector
def mock_save_article(self, article: Dict[str, Any]) -> bool:
    # logger.info(f"  [MOCK SAVE] {article.get('title')[:50]}...")
    return True

BaseCollector._save_article = mock_save_article

# Also mock update_source_stats to avoid DB writes
# Make it robust to args
def mock_update_stats(self, *args, **kwargs):
    pass
BaseCollector._update_source_stats = mock_update_stats

# MOCK FULL TEXT FETCH to speed up verify
import news_collector.utils.full_text
def mock_fetch_full_text_sync(url, session=None):
    return "Mock content for verification speed. " * 100
news_collector.utils.full_text.fetch_full_article = mock_fetch_full_text_sync

# ONE MORE MOCK: Force fresh fetch (ignore DB cache for etags/last-modified)
from news_collector.storage.database import DatabaseManager
def mock_get_metadata(*args, **kwargs):
    return {} # Return empty dict, implies no cached headers
DatabaseManager.get_source_feed_metadata = mock_get_metadata
def mock_update_metadata(*args, **kwargs):
    pass
DatabaseManager.update_source_feed_metadata = mock_update_metadata


from news_collector.collectors.dispatcher import CollectorDispatcher
from news_collector.config.sources import ALL_SOURCES

async def main():
    # print("🚀 Starting LIVE connectivity check for all sources...")
    dispatcher = CollectorDispatcher()
    
    # We will process in chunks to avoid overwhelming or taking too long, 
    # but dispatcher handles parallel tasks.
    
    # Let's run all of them.
    results = await dispatcher.collect_from_multiple_sources_async(ALL_SOURCES)
    
    summary_lines = []
    summary_lines.append("\n📊 LIVE CHECK RESULTS:")
    summary_lines.append("-" * 60)
    summary_lines.append(f"{'Source ID':<20} | {'Type':<10} | {'Status':<10} | {'Articles':<8} | {'Error'}")
    summary_lines.append("-" * 60)
    
    source_details = results.get("source_details", {})
    
    working_count = 0
    total_count = len(ALL_SOURCES)
    
    for source_id, config in ALL_SOURCES.items():
        details = source_details.get(source_id, {})
        success = details.get("success", False)
        articles = details.get("articles_found", 0)
        error = details.get("error_message", "")
        ctype = config.get("collector_type", "rss")
        
        status_icon = "✅ OK" if success and articles > 0 else "⚠️ 0 Art" if success else "❌ FAIL"
        if success and articles > 0:
            working_count += 1
            
        # Truncate error
        if error:
            error = str(error)[:50].replace("\n", " ")
        
        line = f"{source_id:<20} | {ctype:<10} | {status_icon:<10} | {articles:<8} | {error}"
        summary_lines.append(line)
        # print(line)

    summary_lines.append("-" * 60)
    summary_lines.append(f"\n📈 Summary: {working_count}/{total_count} sources are ACTUALLY scraping content right now.")
    
    summary_text = "\n".join(summary_lines)
    print(summary_text)
    
    with open("live_summary.txt", "w") as f:
        f.write(summary_text)

if __name__ == "__main__":
    asyncio.run(main())
