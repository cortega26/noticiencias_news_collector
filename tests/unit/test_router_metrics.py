import unittest
from unittest.mock import patch

from news_collector.enrichment.router import EnrichmentStrategyRouter


class TestRouterMetrics(unittest.TestCase):
    @patch("news_collector.enrichment.router.enrichment_metrics")
    @patch("news_collector.enrichment.router.HttpEnricher")
    def test_http_strategy_records_metrics(self, MockHttp, mock_metrics):
        # Setup
        router = EnrichmentStrategyRouter()
        mock_http_instance = MockHttp.return_value
        mock_http_instance.enrich.return_value = {"success": True, "content": "A" * 600}

        source_config = {"enrichment_strategy": "http"}
        candidate = {"url": "http://example.com"}

        # Execute
        router.route_enrichment("source_1", source_config, candidate)

        # Verify
        mock_metrics.record_attempt.assert_any_call("source_1")
        mock_metrics.record_attempt.assert_any_call("source_1", "http")
        # Success record: source_id, strategy, duration, length, is_publishable
        # We can't verify duration exact value, but we can verify call args
        args, _ = mock_metrics.record_success.call_args
        self.assertEqual(args[0], "source_1")
        self.assertEqual(args[1], "http")
        self.assertEqual(args[3], 600)
        self.assertTrue(args[4])  # is_publishable

    @patch("news_collector.enrichment.router.enrichment_metrics")
    @patch("news_collector.enrichment.router.HeadlessEnricher")
    @patch("news_collector.enrichment.router.HttpEnricher")
    def test_headless_fallback_records_metrics(
        self, MockHttp, MockHeadless, mock_metrics
    ):
        # Setup
        router = EnrichmentStrategyRouter()

        # HTTP fails
        MockHttp.return_value.enrich.return_value = {"success": False}

        # Headless succeeds
        MockHeadless.return_value.enrich.return_value = {
            "success": True,
            "content": "A" * 800,
            "duration": 5.0,
            "raw_content": "...",
        }

        source_config = {
            "enrichment_strategy": "headless_fallback",
            "headless_enabled": True,
        }
        candidate = {"url": "http://example.com"}

        # Execute
        router.route_enrichment("source_2", source_config, candidate)

        # Verify
        # 1. Attempt generic
        mock_metrics.record_attempt.assert_any_call("source_2")
        # 2. Attempt HTTP (first step of fallback)
        mock_metrics.record_attempt.assert_any_call("source_2", "http")
        # 3. Attempt Headless
        mock_metrics.record_attempt.assert_any_call("source_2", "headless")

        # Success (Headless)
        mock_metrics.record_success.assert_called_with(
            "source_2", "headless", 5.0, 800, True
        )

        # Cost recorded
        mock_metrics.record_cost.assert_called_with("source_2", headless_seconds=5.0)


if __name__ == "__main__":
    unittest.main()
