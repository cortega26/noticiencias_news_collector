import unittest

from news_collector.observability.enrichment_metrics_store import EnrichmentMetricsStore


class TestEnrichmentMetricsStore(unittest.TestCase):
    def setUp(self):
        # Use a separate test db or reset the existing one
        self.store = EnrichmentMetricsStore()
        # Hack path for testing to avoid messing with real db?
        # The class uses a hardcoded path. For unit tests, we should probably mock or patch the path.
        # But for now, let's just use the reset method which clears the table.
        self.store.reset()

    def test_record_attempt(self):
        self.store.record_attempt("source_a")
        metrics = self.store.get_metrics("source_a")
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["total_discovered"], 1)
        self.assertEqual(metrics["total_enrichment_attempted"], 1)
        self.assertEqual(metrics["http_attempts"], 0)

        self.store.record_attempt("source_a", strategy="http")
        metrics = self.store.get_metrics("source_a")
        self.assertEqual(metrics["total_discovered"], 2)
        self.assertEqual(metrics["total_enrichment_attempted"], 2)
        self.assertEqual(metrics["http_attempts"], 1)

    def test_record_success_averages(self):
        # Attempt 1
        self.store.record_attempt("source_b")
        self.store.record_success(
            "source_b", "http", duration=10.0, content_length=1000, is_publishable=True
        )

        metrics = self.store.get_metrics("source_b")
        self.assertEqual(metrics["http_success"], 1)
        self.assertEqual(metrics["total_publishable"], 1)
        self.assertEqual(metrics["avg_enrichment_time"], 10.0)
        self.assertEqual(metrics["avg_content_length"], 1000.0)

        # Attempt 2
        self.store.record_attempt("source_b")
        self.store.record_success(
            "source_b", "http", duration=20.0, content_length=2000, is_publishable=False
        )

        metrics = self.store.get_metrics("source_b")
        self.assertEqual(metrics["http_success"], 2)
        self.assertEqual(metrics["total_publishable"], 1)  # No increment
        self.assertEqual(metrics["avg_enrichment_time"], 15.0)  # (10+20)/2
        self.assertEqual(metrics["avg_content_length"], 1500.0)  # (1000+2000)/2

    def test_record_cost(self):
        self.store.record_attempt("source_c")
        self.store.record_cost("source_c", proxy_requests=5, headless_seconds=30.5)

        metrics = self.store.get_metrics("source_c")
        self.assertEqual(metrics["proxy_requests_used"], 5)
        self.assertEqual(metrics["headless_seconds_used"], 30.5)

        self.store.record_cost("source_c", proxy_requests=2, headless_seconds=10.0)
        metrics = self.store.get_metrics("source_c")
        self.assertEqual(metrics["proxy_requests_used"], 7)
        self.assertEqual(metrics["headless_seconds_used"], 40.5)


if __name__ == "__main__":
    unittest.main()
