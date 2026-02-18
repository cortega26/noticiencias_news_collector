
import unittest
from unittest.mock import MagicMock, patch
import os
from news_collector.enrichment.router import EnrichmentStrategyRouter
from news_collector.enrichment.strategy_lock_manager import StrategyLockManager, strategy_lock_manager
from news_collector.observability.enrichment_metrics_store import enrichment_metrics

class TestStrategyLocking(unittest.TestCase):
    def setUp(self):
        # Clean DB state
        with enrichment_metrics._lock:
            enrichment_metrics.cursor.execute("DELETE FROM enrichment_metrics")
            enrichment_metrics.conn.commit()
            
        self.router = EnrichmentStrategyRouter()
        
    def test_lock_overrides_hint_and_config(self):
        source_id = "test_locked_source"
        
        # 1. Config says HTTP
        source_config = {
            "name": source_id,
            "enrichment_strategy": "http",
            "headless_enabled": True
        }
        
        # Mock Optimizer and Lock Manager
        # Note: We need to patch where they are IMPORTED in router.py
        with patch("news_collector.enrichment.router.strategy_optimizer.get_strategy_hint") as mock_hint, \
             patch("news_collector.enrichment.router.strategy_lock_manager.get_lock") as mock_lock, \
             patch.object(self.router.headless, "enrich") as mock_headless, \
             patch.object(self.router, "_execute_http") as mock_http:
            
            mock_http.return_value = {"success": False}
            mock_hint.return_value = "http" # Hint says Stick to HTTP
            
            # Lock says Headless Fallback
            mock_lock.return_value = {"strategy": "headless_fallback"}
            mock_headless.return_value = {"success": True, "content": "Locked Content"*10, "duration": 1.0}

            # Act
            self.router.route_enrichment(source_id, source_config, {"url": "http://example.com"})
            
            # Assert
            # Strategy should be upgraded to headless_fallback despite Hint=HTTP
            self.assertEqual(source_config["enrichment_strategy"], "headless_fallback")
            mock_headless.assert_called()

    def test_lock_respected_only_if_safe(self):
        source_id = "test_unsafe_lock"
        
        # Config: Headless DISABLED
        source_config = {
            "name": source_id,
            "enrichment_strategy": "http",
            "headless_enabled": False
        }
        
        with patch("news_collector.enrichment.router.strategy_lock_manager.get_lock") as mock_lock, \
             patch.object(self.router.headless, "enrich") as mock_headless, \
             patch.object(self.router, "_execute_http") as mock_http:
            
            mock_http.return_value = {"success": True}
            
            # Lock says Headless
            mock_lock.return_value = {"strategy": "headless_fallback"}
            
            # Act
            self.router.route_enrichment(source_id, source_config, {"url": "http://example.com"})
            
            # Assert
            # Should remain http because headless_enabled is False
            self.assertEqual(source_config["enrichment_strategy"], "http")
            mock_headless.assert_not_called()

    def test_scholarly_lock(self):
        source_id = "test_nature_lock"
        source_config = {"name": source_id, "enrichment_strategy": "http"}
        
        with patch("news_collector.enrichment.router.strategy_lock_manager.get_lock") as mock_lock, \
             patch.object(self.router.scholarly, "enrich_url") as mock_scholarly:
                 
            mock_lock.return_value = {"strategy": "scholarly"}
            mock_scholarly.return_value = {"success": True, "content": "DOI Metadata"}
            
            self.router.route_enrichment(source_id, source_config, {"url": "http://nature.com/123"})
            
            self.assertEqual(source_config["enrichment_strategy"], "scholarly")
            mock_scholarly.assert_called()

if __name__ == "__main__":
    unittest.main()
