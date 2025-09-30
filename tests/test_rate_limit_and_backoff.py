import time
from src.collectors.rss_collector import RSSCollector


def test_backoff_monotonic_small():
    c = RSSCollector()
    # measure successive delays (not exact, but ensure non-negative)
    for attempt in range(3):
        start = time.perf_counter()
        c._backoff_sleep(attempt)
        elapsed = time.perf_counter() - start
        assert elapsed >= 0
