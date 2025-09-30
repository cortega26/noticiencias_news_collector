import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import RATE_LIMITING_CONFIG
from src.collectors.async_rss_collector import AsyncRSSCollector


@pytest.fixture()
def anyio_backend():
    return "asyncio"


class DummyDB:
    def __init__(self):
        self.metadata: Dict[str, Dict[str, Any]] = {}

    def get_source_feed_metadata(self, source_id: str) -> Dict[str, Any]:
        return self.metadata.get(
            source_id, {"etag": None, "last_modified": None}
        )

    def update_source_feed_metadata(
        self,
        source_id: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        entry = self.metadata.setdefault(
            source_id, {"etag": None, "last_modified": None}
        )
        if etag is not None:
            entry["etag"] = etag
        if last_modified is not None:
            entry["last_modified"] = last_modified

    def update_source_stats(self, source_id: str, stats: Dict[str, Any]) -> None:  # pragma: no cover - unused in tests
        self.metadata.setdefault(source_id, {})

    def save_article(self, article: Dict[str, Any]):  # pragma: no cover - compatibility
        return article


class DummyAsyncResponse:
    def __init__(self, status_code: int, headers: Dict[str, str], text: str):
        self.status_code = status_code
        self.headers = headers
        self._text = text

    @property
    def text(self) -> str:
        return self._text

    @property
    def content(self) -> bytes:
        return self._text.encode("utf-8")

    def raise_for_status(self) -> None:
        if 400 <= self.status_code < 600:
            raise httpx.HTTPStatusError(
                "HTTP error",
                request=httpx.Request("GET", "https://example.com"),
                response=httpx.Response(self.status_code),
            )


class DummyAsyncClient:
    def __init__(self, response: DummyAsyncResponse):
        self.response = response
        self.captured_headers: Dict[str, str] | None = None

    async def get(self, url: str, timeout: float, headers: Dict[str, str] | None = None):
        self.captured_headers = headers or {}
        return self.response


@pytest.fixture()
def async_collector(monkeypatch: pytest.MonkeyPatch) -> AsyncRSSCollector:
    collector = AsyncRSSCollector()
    dummy_db = DummyDB()
    collector.db_manager = dummy_db
    monkeypatch.setattr(collector, "_send_to_dlq", lambda *args, **kwargs: None)
    return collector


@pytest.mark.anyio
async def test_async_fetch_feed_uses_conditional_headers(
    async_collector: AsyncRSSCollector,
):
    async_collector.db_manager.update_source_feed_metadata(
        "source1",
        etag='"old"',
        last_modified="Wed, 21 Oct 2015 07:28:00 GMT",
    )

    response = DummyAsyncResponse(
        200,
        headers={
            "ETag": '"fresh"',
            "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT",
            "content-type": "application/rss+xml",
        },
        text="<rss></rss>",
    )
    client = DummyAsyncClient(response)

    content, status = await async_collector._fetch_feed_async(
        client, "source1", "https://example.com/feed"
    )

    assert status == 200
    assert content == "<rss></rss>"
    assert client.captured_headers is not None
    assert client.captured_headers["If-None-Match"] == '"old"'
    assert client.captured_headers["If-Modified-Since"] == "Wed, 21 Oct 2015 07:28:00 GMT"

    updated = async_collector.db_manager.get_source_feed_metadata("source1")
    assert updated["etag"] == '"fresh"'
    assert updated["last_modified"] == "Mon, 01 Jan 2024 00:00:00 GMT"


@pytest.mark.anyio
async def test_async_collector_serializes_per_domain_requests(
    async_collector: AsyncRSSCollector, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Ensure deterministic delays
    monkeypatch.setattr("random.uniform", lambda _a, _b: 0.0)
    monkeypatch.setitem(RATE_LIMITING_CONFIG, "domain_default_delay", 1.0)
    monkeypatch.setitem(RATE_LIMITING_CONFIG, "delay_between_requests", 0.5)

    async def allow_all(self, client, url):
        return (True, None)

    async def fake_fetch(self, client, source_id, url):
        return ("<rss></rss>", 200)

    monkeypatch.setattr(AsyncRSSCollector, "_arespect_robots", allow_all, raising=False)
    monkeypatch.setattr(
        AsyncRSSCollector, "_fetch_feed_async", fake_fetch, raising=False
    )
    monkeypatch.setattr(
        AsyncRSSCollector,
        "_extract_articles_from_feed",
        lambda self, parsed_feed, source_config: [],
        raising=False,
    )
    monkeypatch.setattr(
        "feedparser.parse", lambda content: type("Dummy", (), {"bozo": 0})()
    )

    current_time = {"value": 1000.0}
    sleeps: List[float] = []

    def fake_time():
        return current_time["value"]

    async def fake_sleep(duration: float):
        sleeps.append(duration)
        current_time["value"] += duration

    monkeypatch.setattr("time.time", fake_time)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    sources = {
        "src-a": {
            "name": "Example A",
            "url": "https://example.com/feed-a",
            "category": "test",
            "credibility_score": 0.5,
        },
        "src-b": {
            "name": "Example B",
            "url": "https://example.com/feed-b",
            "category": "test",
            "credibility_score": 0.5,
        },
    }

    await async_collector.collect_from_multiple_sources_async(sources)

    assert sleeps == pytest.approx([1.0])
    assert async_collector._domain_next_time["example.com"] == pytest.approx(
        current_time["value"]
    )
