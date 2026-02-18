
import unittest
import os
import shutil
import yaml
from unittest.mock import patch, MagicMock
from news_collector.infrastructure.run_context import RunContextManager
from news_collector.observability.enrichment_metrics_store import EnrichmentMetricsStore
from news_collector.enrichment.strategy_lock_manager import StrategyLockManager
from news_collector.enrichment.router import EnrichmentStrategyRouter

class TestContinuousInvariants(unittest.TestCase):

    def setUp(self):
        # Reset Singletons
        RunContextManager._instance = None
        EnrichmentMetricsStore._instance = None
        StrategyLockManager._instance = None
        
        self.test_dir = "data/metrics/test_invariants"
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        self.lock_file = "news_collector/config/test_invariant_locks.yaml"

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        if os.path.exists(self.lock_file):
            os.remove(self.lock_file)

    def test_run_id_uniqueness(self):
        """Invariant: Each initialization of RunContext generates a unique ID."""
        # Run 1
        RunContextManager._instance = None
        ctx1 = RunContextManager().get_context()
        id1 = ctx1["run_id"]
        
        # Run 2
        RunContextManager._instance = None
        ctx2 = RunContextManager().get_context()
        id2 = ctx2["run_id"]
        
        self.assertNotEqual(id1, id2, "Run IDs must be unique across initializations")

    def test_metrics_path_production(self):
        """Invariant: ENV=production forces metrics to data/metrics/production/"""
        # Reset Store singleton
        EnrichmentMetricsStore._instance = None
        
        # Override Environment on the existing singleton
        from news_collector.infrastructure.run_context import run_context
        # Save old env to restore in tearDown if needed, but tearDown handles dir cleanup
        old_env = run_context.environment
        run_context.set_environment("production")
        
        try:
            # Init Store (which inits DB)
            store = EnrichmentMetricsStore()
            
            expected_path = "data/metrics/production/enrichment_metrics.db"
            self.assertEqual(store.db_path, expected_path, "Must use production DB path when ENV=production")
        finally:
            run_context.set_environment(old_env)


    @patch("news_collector.enrichment.router.strategy_lock_manager")
    @patch("news_collector.enrichment.router.strategy_optimizer")
    @patch("news_collector.enrichment.router.enrichment_metrics")
    def test_lock_priority_over_hint(self, mock_metrics, mock_optimizer, mock_lock_manager):
        """Invariant: Strategy Lock > Optimizer Hint."""
        
        # Setup Router (it doesn't accept args, uses patched globals)
        router = EnrichmentStrategyRouter(logger_factory=MagicMock())
        
        # Mock Lock Manager: Returns a lock
        mock_lock_manager.get_lock.return_value = {"strategy": "headless_fallback"}
        
        # Mock Optimizer: Returns a conflicting hint
        mock_optimizer.get_strategy_hint.return_value = "http"
        
        # Mock Source Config
        source_config = {"id": "test_source", "enrichment_strategy": "scholarly", "headless_enabled": True}
        candidate = {"url": "http://example.com"}
        
        # Mock internal execution to avoid network
        router._execute_http = MagicMock(return_value={"success": True})
        # Mock headless enricher
        router.headless.enrich = MagicMock(return_value={"success": True, "content": "xxxx", "duration": 0.1})
        
        # Force HTTP failure if headless_fallback logic tries HTTP first
        router._execute_http.return_value = {"success": False}
        
        result = router.route_enrichment("test_source", source_config, candidate)
        
        # Verify Lock (headless) won. 
        # Since we forced HTTP failure, it should have tried headless.
        self.assertEqual(result.get("strategy_used"), "headless", "Should use headless strategy due to lock")
        mock_lock_manager.get_lock.assert_called()

    @patch("news_collector.enrichment.router.strategy_lock_manager")
    @patch("news_collector.enrichment.router.strategy_optimizer")
    @patch("news_collector.enrichment.router.enrichment_metrics")
    def test_safety_check_overrides_lock(self, mock_metrics, mock_optimizer, mock_lock_manager):
        """Invariant: Safety Flags > Strategy Lock."""
        
        router = EnrichmentStrategyRouter(logger_factory=MagicMock())
        
        # Lock says Headless
        mock_lock_manager.get_lock.return_value = {"strategy": "headless_fallback"}
        
        # Config says Safety OFF
        source_config = {"id": "test_source", "enrichment_strategy": "http", "headless_enabled": False}
        candidate = {"url": "http://example.com"}
        
        # HTTP returns generic failure (strategy_used='http')
        router._execute_http = MagicMock(return_value={"success": False, "strategy_used": "http"})
        
        result = router.route_enrichment("test_source", source_config, candidate)
        
        # Should NOT use headless. Should have fallen back to original config (http)
        self.assertEqual(result.get("strategy_used"), "http", "Should fallback to config strategy (http) when lock is unsafe")

if __name__ == "__main__":
    unittest.main()
