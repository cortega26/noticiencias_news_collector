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

    def test_discovery_only_skips_article_fetch(self):
        source_config = {
            "enrichment_strategy": "discovery_only",
            "content_mode": "summary_only",
        }
        cand = {"url": "http://example.com/summary-only-article"}

        result = self.router.route_enrichment("src", source_config, cand)

        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "discovery_only")
        self.assertEqual(result["strategy_used"], "none")
        self.router.http.enrich.assert_not_called()
        self.router.headless.enrich.assert_not_called()
        self.router.scholarly.enrich_url.assert_not_called()
        self.router.scrapling.enrich.assert_not_called()

    def test_rss_only_does_not_gate_the_configured_strategy(self):
        source_config = {
            "enrichment_strategy": "http",
            "fetch_mode": "rss_only",
            "content_mode": "summary_only",
        }
        cand = {"url": "http://example.com/article"}
        self.router.http.enrich.return_value = {
            "success": True,
            "content": "A" * 600,
            "raw_content": "<html>...</html>",
        }

        result = self.router.route_enrichment("src", source_config, cand)

        self.assertTrue(result["success"])
        self.assertEqual(result["strategy_used"], "http")
        self.router.http.enrich.assert_called_once()

    def test_summary_only_alone_does_not_skip(self):
        source_config = {
            "enrichment_strategy": "http",
            "content_mode": "summary_only",
        }
        cand = {"url": "http://example.com/article"}
        self.router.http.enrich.return_value = {
            "success": True,
            "content": "A" * 600,
            "raw_content": "<html>...</html>",
        }

        result = self.router.route_enrichment("src", source_config, cand)

        self.assertTrue(result["success"])
        self.assertEqual(result["strategy_used"], "http")
        self.router.http.enrich.assert_called_once()

    def test_missing_url_returns_none(self):
        result = self.router.route_enrichment(
            "src", {"enrichment_strategy": "http"}, {}
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "missing_url")
        self.assertEqual(result["strategy_used"], "none")

    def test_scholarly_failure_returns_reason(self):
        source_config = {"enrichment_strategy": "scholarly"}
        self.router.scholarly.enrich_url.return_value = {
            "success": False,
            "reason": "upstream_503",
        }

        result = self.router.route_enrichment("src", source_config, {"url": "http://x"})

        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "upstream_503")
        self.assertEqual(result["strategy_used"], "scholarly")

    def test_headless_fallback_short_content_is_rejected(self):
        source_config = {
            "enrichment_strategy": "headless_fallback",
            "headless_enabled": True,
        }
        self.router.http.enrich.return_value = {"success": False, "error": "403"}
        self.router.headless.enrich.return_value = {
            "success": True,
            "content": "Too short",
            "duration": 0.1,
        }

        result = self.router.route_enrichment("src", source_config, {"url": "http://x"})

        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "content_too_short_headless")
        self.assertEqual(result["strategy_used"], "headless")

    def test_headless_fallback_budget_exhausted(self):
        source_config = {
            "enrichment_strategy": "headless_fallback",
            "headless_enabled": True,
        }
        self.router.http.enrich.return_value = {"success": False, "error": "403"}
        self.router.headless.enrich.return_value = {
            "success": False,
            "error": "headless_budget_exhausted",
            "duration": 1.2,
        }

        result = self.router.route_enrichment("src", source_config, {"url": "http://x"})

        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "headless_budget_exhausted")
        self.router.logger.error.assert_not_called()

    def test_headless_fallback_generic_failure_logs_error(self):
        source_config = {
            "enrichment_strategy": "headless_fallback",
            "headless_enabled": True,
        }
        self.router.http.enrich.return_value = {"success": False, "error": "403"}
        self.router.headless.enrich.return_value = {
            "success": False,
            "error": "headless_crashed",
            "duration": 0.3,
        }

        result = self.router.route_enrichment("src", source_config, {"url": "http://x"})

        self.assertEqual(result["reason"], "headless_crashed")
        self.router.logger.error.assert_called()

    def test_scrapling_http_success(self):
        source_config = {"enrichment_strategy": "scrapling_http"}
        self.router.scrapling_http.enrich.return_value = {
            "success": True,
            "content": "A" * 600,
            "raw_content": "<html>...</html>",
            "duration": 0.2,
        }

        result = self.router.route_enrichment("src", source_config, {"url": "http://x"})

        self.assertTrue(result["success"])
        self.assertEqual(result["strategy_used"], "scrapling_http")

    def test_scrapling_http_short_content_and_failure(self):
        source_config = {"enrichment_strategy": "scrapling_http"}
        url = {"url": "http://x"}

        self.router.scrapling_http.enrich.return_value = {
            "success": True,
            "content": "short",
            "duration": 0.2,
        }
        result = self.router.route_enrichment("src", source_config, url)
        self.assertEqual(result["reason"], "content_too_short")

        self.router.scrapling_http.enrich.return_value = {
            "success": False,
            "error": "scrapling_http_failed",
        }
        result = self.router.route_enrichment("src", source_config, url)
        self.assertEqual(result["reason"], "scrapling_http_failed")

    def test_scrapling_stealth_success(self):
        source_config = {"enrichment_strategy": "scrapling_stealth"}
        self.router.scrapling.enrich.return_value = {
            "success": True,
            "content": "A" * 600,
            "raw_content": "<html>...</html>",
            "duration": 0.2,
        }

        result = self.router.route_enrichment("src", source_config, {"url": "http://x"})

        self.assertTrue(result["success"])
        self.assertEqual(result["strategy_used"], "scrapling_stealth")

    def test_scrapling_stealth_short_content_and_generic_failure(self):
        source_config = {"enrichment_strategy": "scrapling_stealth"}
        url = {"url": "http://x"}

        self.router.scrapling.enrich.return_value = {
            "success": True,
            "content": "short",
            "duration": 0.2,
        }
        result = self.router.route_enrichment("src", source_config, url)
        self.assertEqual(result["reason"], "content_too_short")

        self.router.scrapling.enrich.return_value = {
            "success": False,
            "error": "connection_reset",
            "duration": 0.2,
        }
        result = self.router.route_enrichment("src", source_config, url)
        self.assertEqual(result["reason"], "connection_reset")
        self.router.logger.error.assert_called()

    def test_strategy_lock_scholarly_is_applied(self):
        source_config = {"enrichment_strategy": "http"}
        self.router.scholarly.enrich_url.return_value = {
            "success": True,
            "content": "Scholarly",
            "metadata": {},
        }

        with patch(
            "news_collector.enrichment.router.strategy_lock_manager.get_lock",
            return_value={"strategy": "scholarly"},
        ):
            result = self.router.route_enrichment(
                "src", source_config, {"url": "http://x"}
            )

        self.assertEqual(result["strategy_used"], "scholarly")

    def test_strategy_lock_proxy_auto_logs_suggestion(self):
        source_config = {"enrichment_strategy": "http"}
        self.router.http.enrich.return_value = {
            "success": True,
            "content": "A" * 600,
            "raw_content": "<html>...</html>",
        }

        with patch(
            "news_collector.enrichment.router.strategy_lock_manager.get_lock",
            return_value={"strategy": "proxy_auto"},
        ):
            result = self.router.route_enrichment(
                "src", source_config, {"url": "http://x"}
            )

        self.assertTrue(result["success"])
        self.router.logger.info.assert_called()

    def test_strategy_lock_scrapling_stealth_when_headless_enabled(self):
        source_config = {"enrichment_strategy": "http", "headless_enabled": True}
        self.router.scrapling.enrich.return_value = {
            "success": True,
            "content": "A" * 600,
            "raw_content": "<html>...</html>",
            "duration": 0.2,
        }

        with patch(
            "news_collector.enrichment.router.strategy_lock_manager.get_lock",
            return_value={"strategy": "scrapling_stealth"},
        ):
            result = self.router.route_enrichment(
                "src", source_config, {"url": "http://x"}
            )

        self.assertEqual(result["strategy_used"], "scrapling_stealth")

    def test_adaptive_hint_consulted_when_not_locked(self):
        source_config = {"enrichment_strategy": "http"}
        self.router.http.enrich.return_value = {
            "success": True,
            "content": "A" * 600,
            "raw_content": "<html>...</html>",
        }

        with (
            patch(
                "news_collector.enrichment.router.strategy_lock_manager.get_lock",
                return_value=None,
            ),
            patch(
                "news_collector.enrichment.router.strategy_optimizer.get_strategy_hint",
                return_value="http",
            ),
        ):
            result = self.router.route_enrichment(
                "src", source_config, {"url": "http://x"}
            )

        self.assertTrue(result["success"])

    def test_strategy_lock_headless_applied(self):
        source_config = {"enrichment_strategy": "http", "headless_enabled": True}
        self.router.http.enrich.return_value = {"success": False, "error": "403"}
        self.router.headless.enrich.return_value = {
            "success": True,
            "content": "A" * 600,
            "duration": 0.1,
        }

        with patch(
            "news_collector.enrichment.router.strategy_lock_manager.get_lock",
            return_value={"strategy": "headless_fallback"},
        ):
            result = self.router.route_enrichment(
                "src", source_config, {"url": "http://x"}
            )

        self.assertEqual(result["strategy_used"], "headless")

    def test_strategy_lock_headless_rejected_when_disabled(self):
        source_config = {"enrichment_strategy": "http", "headless_enabled": False}
        self.router.http.enrich.return_value = {
            "success": True,
            "content": "A" * 600,
            "raw_content": "<html>...</html>",
        }

        with patch(
            "news_collector.enrichment.router.strategy_lock_manager.get_lock",
            return_value={"strategy": "headless_fallback"},
        ):
            result = self.router.route_enrichment(
                "src", source_config, {"url": "http://x"}
            )

        self.assertEqual(result["strategy_used"], "http")

    def test_strategy_lock_http_applied_over_other_strategy(self):
        source_config = {
            "enrichment_strategy": "headless_fallback",
            "headless_enabled": True,
        }
        self.router.http.enrich.return_value = {
            "success": True,
            "content": "A" * 600,
            "raw_content": "<html>...</html>",
        }

        with patch(
            "news_collector.enrichment.router.strategy_lock_manager.get_lock",
            return_value={"strategy": "http"},
        ):
            result = self.router.route_enrichment(
                "src", source_config, {"url": "http://x"}
            )

        self.assertEqual(result["strategy_used"], "http")

    def test_headless_fallback_http_success_short_circuits(self):
        source_config = {
            "enrichment_strategy": "headless_fallback",
            "headless_enabled": True,
        }
        self.router.http.enrich.return_value = {
            "success": True,
            "content": "A" * 600,
            "raw_content": "<html>...</html>",
        }

        result = self.router.route_enrichment("src", source_config, {"url": "http://x"})

        self.assertEqual(result["strategy_used"], "http")
        self.router.headless.enrich.assert_not_called()


if __name__ == "__main__":
    unittest.main()
