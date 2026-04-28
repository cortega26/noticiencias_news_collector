import unittest
from unittest.mock import MagicMock, patch

from news_collector.enrichment.router import EnrichmentStrategyRouter


@patch("news_collector.enrichment.router.enrichment_metrics", MagicMock())
@patch("news_collector.enrichment.router.strategy_lock_manager", MagicMock())
@patch("news_collector.enrichment.router.strategy_optimizer", MagicMock())
class TestEnrichmentStrategyRouter(unittest.TestCase):
    def setUp(self):
        self.router = EnrichmentStrategyRouter()
        self.router.logger = MagicMock()
        self.router.scholarly = MagicMock()
        self.router.http = MagicMock()
        self.router.headless = MagicMock()
        self.router.scrapling = MagicMock()
        self.router.scrapling_http = MagicMock()

    def test_scholarly_strategy(self):
        source_config = {"enrichment_strategy": "scholarly"}
        cand = {"url": "http://example.com/paper"}

        self.router.scholarly.enrich_url.return_value = {
            "success": True,
            "content": "Scholarly Content",
            "metadata": {"doi": "123"},
        }

        result = self.router.route_enrichment("src", source_config, cand)

        self.assertTrue(result["success"])
        self.assertEqual(result["content"], "Scholarly Content")
        self.assertEqual(result["metadata"]["doi"], "123")
        self.assertEqual(result["strategy_used"], "scholarly")
        self.router.scholarly.enrich_url.assert_called_with("http://example.com/paper")

    def test_http_strategy_success(self):
        source_config = {"enrichment_strategy": "http"}
        cand = {"url": "http://example.com/news"}

        self.router.http.enrich.return_value = {
            "success": True,
            "content": "A" * 600,
            "raw_content": "<html>...</html>",
        }

        result = self.router.route_enrichment("src", source_config, cand)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["content"]), 600)
        self.assertEqual(result["strategy_used"], "http")

    def test_http_strategy_too_short(self):
        source_config = {"enrichment_strategy": "http"}
        cand = {"url": "http://example.com/short"}

        self.router.http.enrich.return_value = {
            "success": True,
            "content": "Short",
            "raw_content": "<html>S</html>",
        }

        result = self.router.route_enrichment("src", source_config, cand)

        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "content_too_short_http")

    def test_headless_fallback_success_after_http_fail(self):
        source_config = {
            "enrichment_strategy": "headless_fallback",
            "headless_enabled": True,
        }
        cand = {"url": "http://example.com/js-site"}

        # HTTP fails (too short or 403)
        self.router.http.enrich.return_value = {
            "success": True,
            "content": "Short",
            "raw_content": "<html>JS required</html>",
        }

        # Headless succeeds
        self.router.headless.enrich.return_value = {
            "success": True,
            "content": "A" * 600,
            "raw_content": "<html>rendered</html>",
        }

        result = self.router.route_enrichment("src", source_config, cand)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["content"]), 600)
        self.assertEqual(result["strategy_used"], "headless")
        self.router.headless.enrich.assert_called_once()

    def test_headless_fallback_disabled_config(self):
        source_config = {
            "enrichment_strategy": "headless_fallback",
            "headless_enabled": False,
        }
        cand = {"url": "http://example.com/js-site"}

        self.router.http.enrich.return_value = {"success": False, "error": "403"}

        result = self.router.route_enrichment("src", source_config, cand)

        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "headless_disabled_config")
        self.router.headless.enrich.assert_not_called()

    def test_scrapling_disabled_summary_only_logs_info_with_fallback(self):
        source_config = {
            "enrichment_strategy": "scrapling_stealth",
            "content_mode": "summary_only",
        }
        cand = {"url": "http://example.com/fallback"}

        self.router.scrapling.enrich.return_value = {
            "success": False,
            "error": "scrapling_disabled",
            "duration": 0.2,
        }

        result = self.router.route_enrichment("src", source_config, cand)

        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "scrapling_disabled")
        self.router.logger.info.assert_any_call(
            {
                "event": "enrichment.scrapling.skipped",
                "details": {
                    "source_id": "src",
                    "url": "http://example.com/fallback",
                    "reason": "scrapling_disabled",
                    "fallback": "summary_only",
                },
            }
        )
        self.router.logger.error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
