"""Unit tests for per-host article-enrichment pacing (plan 116).

All timing uses an injected fake clock/sleep seam — no test sleeps for
real (house pattern: the tenacity ``nap.sleep`` seam).
"""

import threading
import unittest
from unittest.mock import MagicMock, patch

from news_collector.enrichment.host_pacer import HostPacer
from news_collector.enrichment.router import EnrichmentStrategyRouter


class FakeClock:
    """Manual clock where sleep advances time (deterministic pacing)."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _pacer(clock: FakeClock, **kwargs) -> HostPacer:
    kwargs.setdefault("min_interval_seconds", 1.5)
    kwargs.setdefault("max_concurrency", 1)
    return HostPacer(clock=clock.clock, sleep=clock.sleep, **kwargs)


class TestHostPacer(unittest.TestCase):
    def test_first_request_never_waits(self):
        clock = FakeClock()
        pacer = _pacer(clock)
        with pacer.pace("https://example.com/a"):
            pass
        self.assertEqual(clock.sleeps, [])

    def test_second_request_to_same_host_waits_interval(self):
        clock = FakeClock()
        pacer = _pacer(clock)
        with pacer.pace("https://example.com/a"):
            pass
        with pacer.pace("https://example.com/b"):
            pass
        self.assertEqual(len(clock.sleeps), 1)
        self.assertAlmostEqual(clock.sleeps[0], 1.5)

    def test_different_hosts_do_not_block_each_other(self):
        clock = FakeClock()
        pacer = _pacer(clock)
        with pacer.pace("https://a.example/x"):
            pass
        with pacer.pace("https://b.example/y"):
            pass
        self.assertEqual(clock.sleeps, [])

    def test_host_matching_is_case_insensitive(self):
        clock = FakeClock()
        pacer = _pacer(clock)
        with pacer.pace("https://EXAMPLE.com/a"):
            pass
        with pacer.pace("https://example.com/b"):
            pass
        self.assertEqual(len(clock.sleeps), 1)

    def test_invalid_url_fails_open_without_pacing(self):
        clock = FakeClock()
        pacer = _pacer(clock)
        with pacer.pace("not-a-url"):
            pass
        with pacer.pace(""):
            pass
        self.assertEqual(clock.sleeps, [])

    def test_disabled_knobs_preserve_current_behavior(self):
        clock = FakeClock()
        pacer = HostPacer(
            min_interval_seconds=0,
            max_concurrency=0,
            clock=clock.clock,
            sleep=clock.sleep,
        )
        self.assertFalse(pacer.enabled)
        for _ in range(3):
            with pacer.pace("https://example.com/a"):
                pass
        self.assertEqual(clock.sleeps, [])

    def test_zero_interval_with_cap_only_enforces_cap(self):
        clock = FakeClock()
        pacer = _pacer(clock, min_interval_seconds=0, max_concurrency=2)
        self.assertTrue(pacer.enabled)
        with pacer.pace("https://example.com/a"):
            pass
        with pacer.pace("https://example.com/a"):
            pass
        self.assertEqual(clock.sleeps, [])

    def test_failure_releases_the_slot(self):
        clock = FakeClock()
        pacer = _pacer(clock, max_wait_seconds=5.0)
        with self.assertRaises(RuntimeError):
            with pacer.pace("https://example.com/a"):
                raise RuntimeError("fetch blew up")
        # Slot must be free again: a non-blocking acquire succeeds.
        slot = pacer._slot_for("example.com")
        assert slot.semaphore is not None
        self.assertTrue(slot.semaphore.acquire(blocking=False))
        slot.semaphore.release()

    def test_concurrency_cap_is_respected_across_threads(self):
        pacer = HostPacer(
            min_interval_seconds=0, max_concurrency=1, max_wait_seconds=10.0
        )
        entered: list[str] = []
        release_first = threading.Event()
        second_done = threading.Event()

        def first():
            with pacer.pace("https://example.com/1"):
                entered.append("first")
                release_first.wait(timeout=10)
                entered.append("first-done")

        def second():
            with pacer.pace("https://example.com/2"):
                entered.append("second")
                second_done.set()

        t1 = threading.Thread(target=first)
        t1.start()
        # Wait until the first thread holds the per-host slot.
        for _ in range(1000):
            if entered == ["first"]:
                break
            threading.Event().wait(0.005)
        self.assertEqual(entered, ["first"])
        t2 = threading.Thread(target=second)
        t2.start()
        threading.Event().wait(0.2)
        # Cap of 1: the second fetch must still be waiting for the slot.
        self.assertEqual(entered, ["first"])
        self.assertFalse(second_done.is_set())
        release_first.set()
        t1.join(timeout=10)
        t2.join(timeout=10)
        self.assertTrue(second_done.is_set())
        self.assertEqual(entered, ["first", "first-done", "second"])

    def test_slot_timeout_fails_open_instead_of_deadlocking(self):
        clock = FakeClock()
        pacer = _pacer(clock, min_interval_seconds=0, max_wait_seconds=0.01)
        slot = pacer._slot_for("example.com")
        assert slot.semaphore is not None
        # Wedge the only slot, then prove pace() still yields (bounded wait).
        self.assertTrue(slot.semaphore.acquire(blocking=False))
        try:
            with pacer.pace("https://example.com/a"):
                pass
        finally:
            slot.semaphore.release()
        self.assertEqual(clock.sleeps, [])

    def test_negative_knobs_rejected(self):
        with self.assertRaises(ValueError):
            HostPacer(min_interval_seconds=-1)
        with self.assertRaises(ValueError):
            HostPacer(max_concurrency=-1)
        with self.assertRaises(ValueError):
            HostPacer(max_wait_seconds=-1)


@patch("news_collector.enrichment.router.enrichment_metrics", MagicMock())
@patch("news_collector.enrichment.router.strategy_lock_manager", MagicMock())
@patch("news_collector.enrichment.router.strategy_optimizer", MagicMock())
class TestRouterPacing(unittest.TestCase):
    def _router(self, clock: FakeClock, **kwargs) -> EnrichmentStrategyRouter:
        router = EnrichmentStrategyRouter(
            host_pacer=HostPacer(clock=clock.clock, sleep=clock.sleep, **kwargs)
        )
        router.logger = MagicMock()
        router.http = MagicMock()
        router.scholarly = MagicMock()
        router.headless = MagicMock()
        router.scrapling = MagicMock()
        router.scrapling_http = MagicMock()
        return router

    def test_same_host_second_fetch_waits(self):
        clock = FakeClock()
        router = self._router(clock)
        router.http.enrich.return_value = {
            "success": True,
            "content": "A" * 600,
            "raw_content": "<html/>",
        }
        cfg = {"enrichment_strategy": "http"}
        router.route_enrichment("src", cfg, {"url": "https://example.com/1"})
        router.route_enrichment("src", cfg, {"url": "https://example.com/2"})
        self.assertEqual(len(clock.sleeps), 1)
        self.assertAlmostEqual(clock.sleeps[0], 1.5)

    def test_cross_host_fetches_do_not_wait(self):
        clock = FakeClock()
        router = self._router(clock)
        router.http.enrich.return_value = {
            "success": True,
            "content": "A" * 600,
            "raw_content": "<html/>",
        }
        cfg = {"enrichment_strategy": "http"}
        router.route_enrichment("src", cfg, {"url": "https://a.example/1"})
        router.route_enrichment("src", cfg, {"url": "https://b.example/2"})
        self.assertEqual(clock.sleeps, [])

    def test_failed_fetch_still_paces_and_releases(self):
        clock = FakeClock()
        router = self._router(clock)
        router.http.enrich.return_value = {"success": False, "error": "boom"}
        cfg = {"enrichment_strategy": "http"}
        first = router.route_enrichment("src", cfg, {"url": "https://example.com/1"})
        second = router.route_enrichment("src", cfg, {"url": "https://example.com/2"})
        self.assertFalse(first["success"])
        self.assertFalse(second["success"])
        # Second fetch waited the interval even though the first failed,
        # and the failed slot was released (no hang, interval enforced).
        self.assertEqual(len(clock.sleeps), 1)

    def test_discovery_only_never_touches_the_pacer(self):
        clock = FakeClock()
        router = self._router(clock)
        pacer_spy = MagicMock(wraps=router.host_pacer)
        router.host_pacer = pacer_spy
        result = router.route_enrichment(
            "src",
            {"enrichment_strategy": "discovery_only"},
            {"url": "https://example.com/x"},
        )
        self.assertEqual(result["reason"], "discovery_only")
        pacer_spy.pace.assert_not_called()
        self.assertEqual(clock.sleeps, [])

    def test_disabled_pacer_preserves_unpaced_behavior(self):
        clock = FakeClock()
        router = self._router(
            clock, min_interval_seconds=0, max_concurrency=0
        )
        router.http.enrich.return_value = {
            "success": True,
            "content": "A" * 600,
            "raw_content": "<html/>",
        }
        cfg = {"enrichment_strategy": "http"}
        for i in range(3):
            result = router.route_enrichment(
                "src", cfg, {"url": f"https://example.com/{i}"}
            )
            self.assertTrue(result["success"])
        self.assertEqual(clock.sleeps, [])


if __name__ == "__main__":
    unittest.main()
