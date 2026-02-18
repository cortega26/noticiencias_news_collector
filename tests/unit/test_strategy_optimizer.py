
import unittest
from unittest.mock import MagicMock, patch
from news_collector.enrichment.strategy_optimizer import StrategyOptimizer, strategy_optimizer

class TestStrategyOptimizer(unittest.TestCase):
    def setUp(self):
        # Reset the global instance's metrics store mock for each test?
        # Better to instantiate a fresh one or mock the property.
        self.optimizer = StrategyOptimizer()
        self.optimizer.metrics_store = MagicMock()

    def test_analyze_source_insufficient_data(self):
        self.optimizer.metrics_store.get_metrics.return_value = None
        result = self.optimizer.analyze_source("source_new")
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["recommended_strategy"], "auto")

    def test_recommend_http_baseline(self):
        # 10 attempts, 9 success via HTTP
        self.optimizer.metrics_store.get_metrics.return_value = {
            "total_enrichment_attempted": 10,
            "total_publishable": 9,
            "http_attempts": 10,
            "http_success": 9,
            "headless_attempts": 0,
            "headless_success": 0
        }
        result = self.optimizer.analyze_source("source_good_http")
        self.assertEqual(result["recommended_strategy"], "http")
        self.assertIn("high_http_yield", result["reason"])

    def test_recommend_headless_fallback(self):
        # 20 attempts
        # HTTP: 10 attempts, 1 success (10%)
        # Headless: 10 attempts, 8 success (80%)
        # Total yield: 9/20 = 45%
        self.optimizer.metrics_store.get_metrics.return_value = {
            "total_enrichment_attempted": 20,
            "total_publishable": 9,
            "http_attempts": 10,
            "http_success": 1,
            "headless_attempts": 10,
            "headless_success": 8,
            "proxy_attempts": 0
        }
        result = self.optimizer.analyze_source("source_needs_headless")
        self.assertEqual(result["recommended_strategy"], "headless_fallback")
        self.assertIn("headless_yield", result["reason"])
        
    def test_recommend_proxy(self):
        # Proxy > Headless > HTTP
        self.optimizer.metrics_store.get_metrics.return_value = {
            "total_enrichment_attempted": 30,
            "total_publishable": 10,
            "http_attempts": 10, "http_success": 0,
            "headless_attempts": 10, "headless_success": 0,
            "proxy_attempts": 10, "proxy_success": 9
        }
        result = self.optimizer.analyze_source("source_needs_proxy")
        self.assertEqual(result["recommended_strategy"], "proxy_auto")
        self.assertIn("proxy_yield", result["reason"])

    def test_recommend_review(self):
        # Very low yield everywhere
        self.optimizer.metrics_store.get_metrics.return_value = {
            "total_enrichment_attempted": 50,
            "total_publishable": 1,
            "http_attempts": 50, "http_success": 1
        }
        result = self.optimizer.analyze_source("source_broken")
        self.assertEqual(result["recommended_strategy"], "review_source")
        self.assertEqual(result["reason"], "very_low_yield")

if __name__ == "__main__":
    unittest.main()
