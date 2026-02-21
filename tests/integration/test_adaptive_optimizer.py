import unittest
from unittest.mock import patch

from news_collector.enrichment.router import EnrichmentStrategyRouter
from news_collector.observability.enrichment_metrics_store import (
    enrichment_metrics,
)


class TestAdaptiveOptimizerIntegration(unittest.TestCase):
    def setUp(self):
        # Reset singleton state
        # We need to monkeypatch the underlying connection or just use a fresh memory DB?
        # The singleton is already alive. We can clear tables?
        from news_collector.observability.enrichment_metrics_store import (
            production_metrics_view,
        )

        production_metrics_view.db_path = enrichment_metrics.db_path
        production_metrics_view.conn = None

        with enrichment_metrics._lock:
            enrichment_metrics.cursor.execute("DELETE FROM enrichment_metrics")
            enrichment_metrics.conn.commit()

        self.router = EnrichmentStrategyRouter()

    def test_adaptive_hint_application(self):
        source_id = "source_test_adaptive"

        # 1. Simulate History: HTTP failing, Headless succeeding
        # We manually seed the metrics store to simulate a history
        # 10 attempts total. 10 HTTP attempts, 0 success.
        # 10 Headless attempts, 9 success.

        with enrichment_metrics._lock:
            # Manually insert for test speed
            # Ensure avg_content_length etc are set to avoid constraints
            enrichment_metrics.cursor.execute(
                """
                INSERT INTO enrichment_metrics (
                    source_id, total_enrichment_attempted, total_publishable,
                    http_attempts, http_success,
                    headless_attempts, headless_success,
                    avg_enrichment_time, avg_content_length, total_discovered
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (source_id, 20, 9, 10, 0, 10, 9, 1.5, 600, 20),
            )
            enrichment_metrics.conn.commit()

        # 2. Configure Source as HTTP initially
        source_config = {
            "name": source_id,
            "enrichment_strategy": "http",
            "headless_enabled": True,  # Must be enabled to accept hint
        }
        candidate = {"url": "http://example.com/article"}

        # 3. Router Execution
        with (
            patch.object(self.router, "_execute_http") as mock_http,
            patch.object(self.router.headless, "enrich") as mock_headless,
        ):

            mock_http.return_value = {"success": False}
            mock_headless.return_value = {
                "success": True,
                "content": "A" * 600,
                "duration": 1.0,
            }

            # Run Router - This should trigger "headless_fallback" logic
            # because the optimizer sees Headless > HTTP
            result = self.router.route_enrichment(source_id, source_config, candidate)

            # 4. Verify Hint Applied
            self.assertEqual(source_config["enrichment_strategy"], "headless_fallback")
            mock_headless.assert_called()

    def test_hint_rejected_if_headless_disabled(self):
        source_id = "source_test_disabled"

        # Seed Metrics: Headless is better
        with enrichment_metrics._lock:
            enrichment_metrics.cursor.execute(
                """
                INSERT INTO enrichment_metrics (
                    source_id, total_enrichment_attempted, total_publishable,
                    http_attempts, http_success,
                    headless_attempts, headless_success
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (source_id, 20, 9, 10, 0, 10, 9),
            )
            enrichment_metrics.conn.commit()

        # Config: Headless Disabled
        source_config = {
            "name": source_id,
            "enrichment_strategy": "http",
            "headless_enabled": False,
        }
        candidate = {"url": "http://example.com/article"}

        with (
            patch.object(self.router, "_execute_http") as mock_http,
            patch.object(self.router.headless, "enrich") as mock_headless,
        ):

            mock_http.return_value = {"success": False}

            result = self.router.route_enrichment(source_id, source_config, candidate)

            # Verify Hint Rejected
            self.assertEqual(source_config["enrichment_strategy"], "http")
            mock_headless.assert_not_called()


if __name__ == "__main__":
    unittest.main()
