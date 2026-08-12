import os
import shutil
import unittest
from unittest.mock import patch

import yaml

from news_collector.enrichment.strategy_lock_manager import strategy_lock_manager
from news_collector.enrichment.strategy_optimizer import strategy_optimizer


class TestContinuousOperation(unittest.TestCase):

    def setUp(self):
        # Setup specific test environment
        self.test_dir = "data/metrics/test_continuous"
        os.makedirs(self.test_dir, exist_ok=True)
        self.lock_file = f"{self.test_dir}/test_strategy_locks.yaml"

        # Reset Singleton
        strategy_lock_manager._locks = {}
        strategy_lock_manager.config_path = self.lock_file
        if os.path.exists(self.lock_file):
            os.remove(self.lock_file)

        # Mock Metrics Store return values
        self.mock_metrics = {
            "source_test_auto_lock": {
                "total_enrichment_attempted": 10,
                "total_publishable": 8,
                "http_attempts": 10,
                "http_success": 0,  # 0% success
                "headless_attempts": 10,
                "headless_success": 8,  # 80% success -> Should Lock
            }
        }

    def tearDown(self):
        if os.path.exists(self.lock_file):
            os.remove(self.lock_file)
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_auto_lock_trigger(self):
        """Verify that StrategyOptimizer triggers a lock when criteria are met."""

        # Mock the metrics store used by logic
        with patch.object(strategy_optimizer.metrics_store, "get_metrics") as mock_get:
            mock_get.side_effect = lambda sid: self.mock_metrics.get(sid)

            # Run analysis
            result = strategy_optimizer.analyze_source("source_test_auto_lock")

            # Verify Lock File Created
            self.assertTrue(
                os.path.exists(self.lock_file), "Lock file should be created"
            )

            with open(self.lock_file, "r") as f:
                data = yaml.safe_load(f)
                locks = data.get("locks", {})
                self.assertIn("source_test_auto_lock", locks)
                self.assertEqual(
                    locks["source_test_auto_lock"]["strategy"], "headless_fallback"
                )
                print("\n✅ Auto-Lock successfully triggered and persisted.")


if __name__ == "__main__":
    unittest.main()
