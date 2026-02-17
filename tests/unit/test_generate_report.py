
import unittest
import os
from unittest.mock import patch, MagicMock
from news_collector.enrichment.strategy_optimizer import StrategyOptimizer

class TestGenerateReport(unittest.TestCase):
    def test_generate_report_content(self):
        optimizer = StrategyOptimizer()
        optimizer.metrics_store = MagicMock()
        
        # Mock metrics for 2 sources
        optimizer.metrics_store.get_all_metrics.return_value = {
            "source_1": {
                "total_enrichment_attempted": 10,
                "total_publishable": 9,
                "http_attempts": 10, "http_success": 9,
                "avg_enrichment_time": 1.5
            },
            "source_2": {
                "total_enrichment_attempted": 10,
                "total_publishable": 2,
                "http_attempts": 5, "http_success": 0,
                "headless_attempts": 5, "headless_success": 2,
                "avg_enrichment_time": 5.0
            }
        }
        
        # Mock get_metrics for individual calls (since analyze_source calls it)
        def get_metrics_side_effect(source_id):
            return optimizer.metrics_store.get_all_metrics.return_value.get(source_id)
            
        optimizer.metrics_store.get_metrics.side_effect = get_metrics_side_effect
        
        report = optimizer.generate_report()
        
        self.assertIn("# Adaptive Enrichment Optimization Report", report)
        self.assertIn("| source_1 |", report)
        self.assertIn("| **http** |", report) # Recommendation
        self.assertIn("| source_2 |", report)
        self.assertIn("| 20.0% |", report) # Yield
        self.assertIn("1.50", report) # Time

if __name__ == "__main__":
    unittest.main()
