import sys
import os
import asyncio
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import NewsCollectorSystem
from news_collector.collectors.async_rss_collector import AsyncRSSCollector
from news_collector.config.settings import COLLECTION_CONFIG

def verify_system_init():
    print("Verifying System Initialization with Async Config...")
    print(f"Async Enabled Config: {COLLECTION_CONFIG.get('async_enabled')}")
    
    system = NewsCollectorSystem()
    system.initialize()
    
    collector = system.collector
    print(f"Collector Type: {type(collector).__name__}")
    
    if isinstance(collector, AsyncRSSCollector):
        print("✅ SUCCESS: System initialized with AsyncRSSCollector")
    else:
        print(f"❌ FAILURE: Expected AsyncRSSCollector, got {type(collector).__name__}")
        sys.exit(1)

    return system

async def verify_collection_execution(system):
    print("\nVerifying Async Collection Cycle (Dry Run)...")
    try:
        # Mocking ALL_SOURCES to process only one known source to save time/bandwidth
        # or just relying on dry_run which simulates?
        # dry_run in main.py calls _simulate_collection unfortunately...
        # We want to test the REAL execution path but dry_run mode usually implies no DB writes.
        # Let's see main.py _execute_collection logic:
        # if dry_run: return self._simulate_collection(sources)
        # So dry_run skips the actual async collector call! 
        # We need to run with dry_run=False but maybe mocked DB or just limited sources.
        
        # Let's just call the collector directly to verify it runs without crashing.
        
        from news_collector.config import ALL_SOURCES
        # Pick a simple source
        test_source_id = list(ALL_SOURCES.keys())[0] if ALL_SOURCES else "test_source"
        test_source = ALL_SOURCES.get(test_source_id) or {"url": "http://example.com/rss", "name": "Test", "category": "general"}
        
        sources = {test_source_id: test_source}
        
        print(f"Testing direct async collection on source: {test_source_id}")
        
        # We invoke collect_from_multiple_sources_async directly
        result = await system.collector.collect_from_multiple_sources_async(sources)
        
        print("Async Collection Result Summary:")
        print(result.get("collection_summary"))
        
        if result.get("source_details", {}).get(test_source_id, {}).get("success") is not None:
             print("✅ SUCCESS: Async collection executed (success/fail outcome is less important than running)")
        else:
             print("❌ FAILURE: No result for source")
             sys.exit(1)
             
    except Exception as e:
        print(f"❌ FAILURE: Exception during async collection: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    system = verify_system_init()
    asyncio.run(verify_collection_execution(system))
