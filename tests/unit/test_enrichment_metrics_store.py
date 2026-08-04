import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from news_collector.observability.enrichment_metrics_store import (
    EnrichmentMetricsStore,
    _apply_success,
)


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

    def test_record_attempt_ignores_untrusted_strategy_text(self):
        self.store.record_attempt("source_d", strategy="http_attempts = 999")
        metrics = self.store.get_metrics("source_d")

        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["total_enrichment_attempted"], 1)
        self.assertEqual(metrics["http_attempts"], 0)
        self.assertEqual(metrics["headless_attempts"], 0)
        self.assertEqual(metrics["proxy_attempts"], 0)
        self.assertEqual(metrics["scholarly_attempts"], 0)

    def test_record_success_updates_proxy_column(self):
        self.store.record_attempt("source_e", strategy="proxy")
        self.store.record_success(
            "source_e", "proxy", duration=8.0, content_length=800, is_publishable=True
        )

        metrics = self.store.get_metrics("source_e")
        self.assertEqual(metrics["proxy_success"], 1)
        self.assertEqual(metrics["http_success"], 0)
        self.assertEqual(metrics["headless_success"], 0)
        self.assertEqual(metrics["scholarly_success"], 0)

    def test_scrapling_http_maps_to_http_metrics_bucket(self):
        with patch(
            "news_collector.observability.enrichment_metrics_store.logger.warning"
        ) as mock_warning:
            self.store.record_attempt("source_f", strategy="scrapling_http")
            self.store.record_success(
                "source_f",
                "scrapling_http",
                duration=4.0,
                content_length=900,
                is_publishable=True,
            )

        metrics = self.store.get_metrics("source_f")
        self.assertEqual(metrics["http_attempts"], 1)
        self.assertEqual(metrics["http_success"], 1)
        mock_warning.assert_not_called()

    def test_scrapling_stealth_maps_to_headless_metrics_bucket(self):
        with patch(
            "news_collector.observability.enrichment_metrics_store.logger.warning"
        ) as mock_warning:
            self.store.record_attempt("source_g", strategy="scrapling_stealth")
            self.store.record_success(
                "source_g",
                "scrapling_stealth",
                duration=6.0,
                content_length=1200,
                is_publishable=False,
            )

        metrics = self.store.get_metrics("source_g")
        self.assertEqual(metrics["headless_attempts"], 1)
        self.assertEqual(metrics["headless_success"], 1)
        mock_warning.assert_not_called()


class TestBufferedFlushEquivalence(unittest.TestCase):
    """Plan 038, Step 3: batching must never change the final aggregate
    values — only when they're written. These tests replay the exact same
    event sequence through an immediate (batch_size=1) store and a batched
    (batch_size=100, one flush at the end) store, and assert byte-identical
    final rows.
    """

    def _replay(self, store: EnrichmentMetricsStore) -> None:
        # Interleaved attempts/successes, including two attempts in a row
        # with no matching success (failures elsewhere) — this is the
        # scenario that distinguishes "replay events in order" (correct)
        # from "coalesce sum(durations)/count(successes)" (wrong): an
        # attempt with no success still bumps the divisor.
        store.record_attempt("source_interleave", strategy="http")
        store.record_success(
            "source_interleave",
            "http",
            duration=10.0,
            content_length=100,
            is_publishable=True,
        )
        store.record_attempt("source_interleave", strategy="http")
        store.record_success(
            "source_interleave",
            "http",
            duration=20.0,
            content_length=200,
            is_publishable=False,
        )
        store.record_attempt("source_interleave", strategy="http")
        store.record_attempt("source_interleave", strategy="http")
        store.record_success(
            "source_interleave",
            "http",
            duration=30.0,
            content_length=300,
            is_publishable=True,
        )

    def test_interleaved_attempts_and_successes_match_between_immediate_and_batched(
        self,
    ):
        tmpdir = tempfile.mkdtemp()
        immediate = EnrichmentMetricsStore.create_isolated(
            environment="test",
            db_path=str(Path(tmpdir) / "immediate.db"),
            flush_batch_size=1,
        )
        batched = EnrichmentMetricsStore.create_isolated(
            environment="test",
            db_path=str(Path(tmpdir) / "batched.db"),
            flush_batch_size=100,
        )
        try:
            self._replay(immediate)
            self._replay(batched)
            batched.flush()  # fewer than 100 events accumulated; flush explicitly

            immediate_row = immediate.get_metrics("source_interleave")
            batched_row = batched.get_metrics("source_interleave")

            assert immediate_row is not None and batched_row is not None
            # The worked counter-example: avg is NOT (10+20+30)/3 == 20.0.
            # 4 attempts were recorded but only 3 successes — the running
            # average divides by the attempt count at each success, so the
            # correct value replays to 18.75, not a plain mean.
            self.assertEqual(immediate_row["avg_enrichment_time"], 18.75)
            self.assertEqual(batched_row["avg_enrichment_time"], 18.75)

            for key in immediate_row:
                self.assertEqual(
                    immediate_row[key],
                    batched_row[key],
                    f"Column {key!r} diverged between immediate and batched flush",
                )
        finally:
            immediate.close()
            batched.close()

    def test_forced_flush_failure_neither_corrupts_aggregates_nor_drops_buffer(self):
        tmpdir = tempfile.mkdtemp()
        store = EnrichmentMetricsStore.create_isolated(
            environment="test",
            db_path=str(Path(tmpdir) / "flush_failure.db"),
            flush_batch_size=100,
        )
        try:
            store.record_attempt("source_h", strategy="http")
            store.record_success(
                "source_h", "http", duration=5.0, content_length=50, is_publishable=True
            )

            # sqlite3.Connection.commit is a read-only C slot and can't be
            # patched directly; force the failure via the store's own
            # _upsert_row instead, which flush() calls before committing.
            with patch.object(
                store,
                "_upsert_row",
                side_effect=RuntimeError("simulated disk full"),
            ):
                with self.assertRaises(RuntimeError):
                    store.flush()

            # Buffer survives the failed flush — nothing was silently dropped.
            self.assertEqual(len(store._buffer), 2)

            # A retried flush (commit working again) succeeds and produces
            # the correct, uncorrupted aggregate.
            store.flush()
            metrics = store.get_metrics("source_h")
            assert metrics is not None
            self.assertEqual(metrics["http_success"], 1)
            self.assertEqual(metrics["avg_enrichment_time"], 5.0)
        finally:
            store.close()

    def test_apply_success_returns_none_for_unknown_strategy(self):
        row = {
            "total_enrichment_attempted": 1,
            "avg_enrichment_time": 0.0,
            "avg_content_length": 0.0,
            "total_publishable": 0,
        }
        result = _apply_success(row, "not_a_real_strategy", 1.0, 1, True)
        self.assertIsNone(result)

    def test_reset_reopens_when_database_file_was_removed(self):
        # Regression: the CI cascade removes the metrics directory between
        # test runs, leaving the connection pointing at a deleted file.
        # reset() must re-open (like flush does) instead of failing on a
        # stale, effectively read-only handle.
        tmpdir = tempfile.mkdtemp()
        db_file = Path(tmpdir) / "reset_reopen.db"
        store = EnrichmentMetricsStore.create_isolated(
            environment="test",
            db_path=str(db_file),
            flush_batch_size=100,
        )
        try:
            store.record_attempt("source_i", strategy="http")
            store.flush()
            self.assertEqual(
                store.get_metrics("source_i")["total_enrichment_attempted"], 1
            )

            db_file.unlink()

            store.reset()
            self.assertIsNone(store.get_metrics("source_i"))

            store.record_attempt("source_i", strategy="http")
            metrics = store.get_metrics("source_i")
            self.assertEqual(metrics["total_enrichment_attempted"], 1)
        finally:
            store.close()

    def test_reset_reopens_when_connection_was_closed(self):
        tmpdir = tempfile.mkdtemp()
        db_file = Path(tmpdir) / "reset_reopen_closed.db"
        store = EnrichmentMetricsStore.create_isolated(
            environment="test",
            db_path=str(db_file),
            flush_batch_size=100,
        )
        try:
            store.record_attempt("source_j", strategy="http")
            store.flush()
            store.conn.close()
            store.conn = None

            store.reset()
            store.record_attempt("source_j", strategy="http")
            self.assertEqual(
                store.get_metrics("source_j")["total_enrichment_attempted"], 1
            )
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
