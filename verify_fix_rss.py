import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
import sys
import os

# Add project root to sys.path
sys.path.append(os.getcwd())

from news_collector.collectors.rss_collector import RSSCollector

class TestRSSCollectorFix(unittest.TestCase):
    @patch('news_collector.collectors.base_collector.get_database_manager')
    def test_naive_datetime_handling(self, mock_get_db):
        print("Testing naive datetime handling in RSSCollector...")
        
        # Setup Mock DB Manager
        mock_db_instance = MagicMock()
        mock_get_db.return_value = mock_db_instance
        
        # Mock circuit state with NAIVE datetime in the FUTURE
        naive_future = datetime(3000, 1, 1) # Naive
        
        mock_db_instance.get_source_circuit_state.return_value = {
            "status": "COOLDOWN",
            "next_retry_at": naive_future,
            "consecutive_failures": 3,
            "is_active": True
        }

        # Mock internal dependencies to avoid side effects
        # Valid patch targets based on imports in rss_collector.py
        with patch('news_collector.infrastructure.requests_client.RobustRequestsClient') as MockClient, \
             patch('news_collector.collectors.rss_collector.RssParser') as MockParser, \
             patch('news_collector.collectors.rss_collector.ImageExtractor') as MockImgExtractor, \
             patch('news_collector.collectors.rss_collector.PreScorer') as MockPreScorer:
            
            collector = RSSCollector()
            
            # Verify db_manager is our mock
            self.assertEqual(collector.db_manager, mock_db_instance)

            source_config = {"url": "http://example.com/rss", "name": "Test"}
            
            try:
                # This call triggers the circuit breaker check logic we patched
                stats = collector.collect_from_source("test_source", source_config)
                print("✅ collect_from_source executed without TypeError")
                
                if stats.get("error_message") == "Circuit Breaker: Skipped (Cooldown)":
                    print("✅ Circuit Breaker logic correctly identified Cooldown")
                else:
                    print(f"⚠️ Collected stats: {stats}")

            except TypeError as e:
                print(f"❌ TypeError caught: {e}")
                # This catches the specific error we are fixing: "can't compare offset-naive and offset-aware datetimes"
                raise

if __name__ == "__main__":
    unittest.main()
