import asyncio
from types import MethodType
from typing import Type

import pytest

from src.collectors.async_rss_collector import AsyncRSSCollector
from src.collectors.rss_collector import RSSCollector
from src.perf import MemoryFeedStore


class _BaseResponse:
    status_code: int
    headers: dict[str, str]
    text: str
    content: bytes

    def raise_for_status(self) -> None:  # pragma: no cover - defensive
        return None


class _Response200(_BaseResponse):
    status_code = 200
    headers = {"ETag": "W/\"new\"", "Last-Modified": "Wed, 12 Mar 2025 12:00:00 GMT"}
    text = "<rss></rss>"
    content = b"<rss></rss>"


class _Response304(_BaseResponse):
    status_code = 304
    headers = {"ETag": "W/\"fresh\"", "Last-Modified": "Wed, 12 Mar 2025 12:30:00 GMT"}
    text = ""
    content = b""


class _Response429(_BaseResponse):
    status_code = 429
    headers: dict[str, str] = {}
    text = ""
    content = b""


@pytest.mark.parametrize("response_cls", [_Response200, _Response304])
def test_fetch_feed_applies_conditional_headers(response_cls: Type[_BaseResponse]) -> None:
    collector = RSSCollector()
    store = MemoryFeedStore()
    store.update_source_feed_metadata(
        "source-1", etag="W/\"cached\"", last_modified="Wed, 12 Mar 2025 11:00:00 GMT"
    )
    collector.db_manager = store

    captured: dict[str, dict[str, str]] = {}

    def fake_get(url: str, timeout: float, headers: dict[str, str] | None = None):
        captured["headers"] = headers or {}
        return response_cls()

    collector.session.get = fake_get  # type: ignore[assignment]

    content, status = collector._fetch_feed("source-1", "https://example.com/feed")

    headers = captured["headers"]
    assert headers["If-None-Match"] == "W/\"cached\""
    assert headers["If-Modified-Since"] == "Wed, 12 Mar 2025 11:00:00 GMT"
    if status == 304:
        assert content is None
        assert store.metadata["source-1"]["etag"] == "W/\"fresh\""
    else:
        assert status == 200
        assert store.metadata["source-1"]["etag"] == "W/\"new\""


def test_fetch_feed_invokes_backoff_on_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    collector = RSSCollector()
    store = MemoryFeedStore()
    collector.db_manager = store

    responses = iter([_Response429(), _Response200()])
    attempts: list[int] = []

    def fake_get(url: str, timeout: float, headers: dict[str, str] | None = None):
        return next(responses)

    def fake_backoff(self: RSSCollector, attempt: int) -> None:
        attempts.append(attempt)

    collector.session.get = fake_get  # type: ignore[assignment]
    collector._backoff_sleep = MethodType(fake_backoff, collector)

    content, status = collector._fetch_feed("source-1", "https://example.com/feed")

    assert status == 200
    assert attempts == [0]
    assert store.metadata["source-1"]["etag"] == "W/\"new\""


def test_async_fetch_uses_conditional_headers() -> None:
    collector = AsyncRSSCollector()
    store = MemoryFeedStore()
    collector.db_manager = store
    store.update_source_feed_metadata(
        "source-1", etag="W/\"cached\"", last_modified="Wed, 12 Mar 2025 11:00:00 GMT"
    )

    captured: dict[str, dict[str, str]] = {}

    class MockClient:
        async def get(self, url: str, timeout: float, headers: dict[str, str] | None = None):
            captured["headers"] = headers or {}
            return _Response200()

    async def _run():
        return await collector._fetch_feed_async(
            MockClient(), "source-1", "https://example.com/feed"
        )

    content, status = asyncio.run(_run())

    headers = captured["headers"]
    assert headers["If-None-Match"] == "W/\"cached\""
    assert headers["If-Modified-Since"] == "Wed, 12 Mar 2025 11:00:00 GMT"
    assert status == 200
    assert store.metadata["source-1"]["etag"] == "W/\"new\""


def test_async_fetch_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    collector = AsyncRSSCollector()
    store = MemoryFeedStore()
    collector.db_manager = store

    responses = iter([_Response429(), _Response200()])
    attempts: list[float] = []

    async def fake_sleep(delay: float) -> None:
        attempts.append(delay)

    class MockClient:
        async def get(self, url: str, timeout: float, headers: dict[str, str] | None = None):
            return next(responses)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async def _run():
        return await collector._fetch_feed_async(
            MockClient(), "source-1", "https://example.com/feed"
        )

    content, status = asyncio.run(_run())

    assert status == 200
    assert len(attempts) == 1
    assert store.metadata["source-1"]["etag"] == "W/\"new\""
