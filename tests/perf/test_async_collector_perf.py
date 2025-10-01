import asyncio
import sys
from pathlib import Path
from time import perf_counter, sleep
from typing import Any, Dict

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT.parent))

from config.settings import COLLECTION_CONFIG
from src.collectors.async_rss_collector import AsyncRSSCollector
from src.collectors.rss_collector import RSSCollector


pytestmark = pytest.mark.perf


SIMULATED_FEED = "<rss><channel><item><title>Example</title></item></channel></rss>"
SIMULATED_DELAY = 0.02


class MockDB:
    def __init__(self):
        self.saved = []

    def get_source_feed_metadata(self, source_id: str) -> Dict[str, str | None]:
        return {"etag": None, "last_modified": None}

    def update_source_feed_metadata(
        self,
        source_id: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        return None

    def update_source_stats(self, source_id: str, stats: Dict[str, float]) -> None:
        return None

    def save_article(self, article):
        self.saved.append(article)
        return article


def _stub_common_behaviour(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_feed = type("MockFeed", (), {"bozo": 0})()

    def fake_parse(content: str):
        return fake_feed

    def extract_one(self, parsed_feed, source_config):
        return [
            {
                "url": f"{source_config['url']}#1",
                "title": "Example",
                "summary": "Summary",
            }
        ]

    def process_passthrough(self, raw_article, source_id, source_config):
        return {
            "url": raw_article["url"],
            "title": raw_article["title"],
            "summary": raw_article["summary"],
        }

    monkeypatch.setattr("feedparser.parse", fake_parse)
    monkeypatch.setattr(
        RSSCollector,
        "_extract_articles_from_feed",
        extract_one,
        raising=False,
    )
    monkeypatch.setattr(
        AsyncRSSCollector,
        "_extract_articles_from_feed",
        extract_one,
        raising=False,
    )
    monkeypatch.setattr(
        RSSCollector,
        "_process_article",
        process_passthrough,
        raising=False,
    )
    monkeypatch.setattr(
        AsyncRSSCollector,
        "_process_article",
        process_passthrough,
        raising=False,
    )
    monkeypatch.setattr(
        RSSCollector, "_save_article", lambda self, article: True, raising=False
    )
    monkeypatch.setattr(
        AsyncRSSCollector,
        "_save_article",
        lambda self, article: True,
        raising=False,
    )
    monkeypatch.setattr(RSSCollector, "_respect_robots", lambda self, url: (True, None))

    async def allow_async(self, client, url):
        return (True, None)

    async def noop_async(*args, **kwargs):
        return None

    monkeypatch.setattr(
        AsyncRSSCollector,
        "_arespect_robots",
        allow_async,
        raising=False,
    )
    monkeypatch.setattr(
        RSSCollector,
        "_enforce_domain_rate_limit",
        lambda self, domain, robots_delay, source_min_delay=None: None,
    )
    monkeypatch.setattr(
        AsyncRSSCollector,
        "_a_enforce_domain_rate_limit",
        noop_async,
        raising=False,
    )

    class MockAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: MockAsyncClient())


def _build_sources() -> Dict[str, Dict[str, Any]]:
    return {
        f"source-{idx}": {
            "name": f"Source {idx}",
            "url": f"https://example{idx}.com/feed",
            "category": "perf",
            "credibility_score": 0.5,
        }
        for idx in range(4)
    }


def test_async_collector_outperforms_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(COLLECTION_CONFIG, "max_concurrent_requests", 4)

    _stub_common_behaviour(monkeypatch)

    sync_collector = RSSCollector()
    async_collector = AsyncRSSCollector()

    sync_collector.db_manager = MockDB()
    async_collector.db_manager = MockDB()

    def slow_fetch(self, source_id, feed_url):
        sleep(SIMULATED_DELAY)
        return (SIMULATED_FEED, 200)

    async def slow_fetch_async(self, client, source_id, feed_url):
        await asyncio.sleep(SIMULATED_DELAY)
        return (SIMULATED_FEED, 200)

    monkeypatch.setattr(RSSCollector, "_fetch_feed", slow_fetch, raising=False)
    monkeypatch.setattr(
        AsyncRSSCollector,
        "_fetch_feed_async",
        slow_fetch_async,
        raising=False,
    )

    sources = _build_sources()

    sync_start = perf_counter()
    sync_collector.collect_from_multiple_sources(sources)
    sync_duration = perf_counter() - sync_start

    async_start = perf_counter()
    asyncio.run(async_collector.collect_from_multiple_sources_async(sources))
    async_duration = perf_counter() - async_start

    assert async_duration < sync_duration * 0.7
