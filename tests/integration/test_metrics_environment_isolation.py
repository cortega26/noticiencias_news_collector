import os
import shutil
import sqlite3
import unittest
from unittest.mock import patch

from news_collector.enrichment.strategy_optimizer import StrategyOptimizer
from news_collector.infrastructure.run_context import run_context
from news_collector.observability.enrichment_metrics_store import (
    enrichment_metrics,
)


class TestMetricsEnvironmentIsolation(unittest.TestCase):
    def setUp(self):
        # Reset Context to Test
        run_context.set_environment("test")

        # Clean up test DBs
        self.test_db_dir = "data/metrics/test"
        self.prod_db_dir = "data/metrics/production"

        if os.path.exists(self.test_db_dir):
            shutil.rmtree(self.test_db_dir)
        if os.path.exists(self.prod_db_dir):
            shutil.rmtree(self.prod_db_dir)

        from news_collector.observability.enrichment_metrics_store import (
            production_metrics_view,
        )

        production_metrics_view.db_path = (
            "data/metrics/production/enrichment_metrics.db"
        )
        production_metrics_view.conn = None

        # Re-init singleton (hacky but needed for tests)
        # We can just create new instances since we modified __init__ to check _initialized
        enrichment_metrics._initialized = False
        enrichment_metrics.__init__()  # Re-init to pick up 'test' env

    def test_writes_go_to_correct_env_db(self):
        # Act
        enrichment_metrics.record_attempt("source_test_iso", "http")

        # Assert
        test_db = f"{self.test_db_dir}/enrichment_metrics.db"
        self.assertTrue(os.path.exists(test_db), "Test DB should be created")

        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT * FROM enrichment_metrics WHERE source_id='source_test_iso'")
        self.assertIsNotNone(c.fetchone())
        conn.close()

        # Verify PROD DB does NOT have it
        prod_db = f"{self.prod_db_dir}/enrichment_metrics.db"
        if os.path.exists(prod_db):
            conn = sqlite3.connect(prod_db)
            c = conn.cursor()
            try:
                c.execute(
                    "SELECT * FROM enrichment_metrics WHERE source_id='source_test_iso'"
                )
                self.assertIsNone(
                    c.fetchone(), "Production DB should NOT have test data"
                )
            except sqlite3.OperationalError:
                pass  # Table might not verify exist
            conn.close()

    def test_optimizer_integrity_checks(self):
        # 1. Setup Mock Production Data
        os.makedirs(self.prod_db_dir, exist_ok=True)
        prod_db_path = f"{self.prod_db_dir}/enrichment_metrics.db"
        conn = sqlite3.connect(prod_db_path)
        c = conn.cursor()
        # Create table manually for test setup because ProductionReadonlyStore doesn't create it
        c.execute(
            "CREATE TABLE enrichment_metrics (source_id TEXT PRIMARY KEY, total_enrichment_attempted INTEGER, total_publishable INTEGER, http_attempts INTEGER, http_success INTEGER, headless_attempts INTEGER, headless_success INTEGER, proxy_attempts INTEGER, proxy_success INTEGER, scholarly_attempts INTEGER, scholarly_success INTEGER, total_discovered INTEGER, avg_content_length REAL, avg_enrichment_time REAL, proxy_requests_used INTEGER, headless_seconds_used REAL, last_updated TIMESTAMP)"
        )

        # Insert INSUFFICIENT data (3 attempts)
        c.execute(
            "INSERT INTO enrichment_metrics (source_id, total_enrichment_attempted, total_publishable) VALUES ('source_weak', 3, 3)"
        )

        # Insert SUFFICIENT data (10 attempts)
        c.execute(
            "INSERT INTO enrichment_metrics (source_id, total_enrichment_attempted, total_publishable) VALUES ('source_strong', 10, 10)"
        )
        conn.commit()
        conn.close()

        # 2. Initialize Optimizer
        # Use patch.object to mock the retrieval of context from the singleton instance
        with patch.object(
            run_context,
            "get_context",
            return_value={
                "run_id": "test_run",
                "environment": "production",
                "timestamp": "now",
            },
        ):
            optimizer = StrategyOptimizer()  # Should attach to ProductionReadonlyStore

            # Case A: Weak Source
            analysis = optimizer.analyze_source("source_weak")
            self.assertEqual(
                analysis["status"], "insufficient_data", "Should reject < 5 attempts"
            )
            self.assertEqual(analysis["recommended_strategy"], "auto")

            # Case B: Strong Source
            analysis = optimizer.analyze_source("source_strong")
            self.assertNotEqual(analysis.get("status"), "insufficient_data")
            self.assertTrue(analysis["total_attempts"] >= 5)


if __name__ == "__main__":
    unittest.main()
