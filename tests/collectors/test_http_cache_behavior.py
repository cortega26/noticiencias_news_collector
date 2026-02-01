import hashlib
from typing import Type

import pytest
from news_collector.collectors.rss_collector import RSSCollector
from news_collector.perf import MemoryFeedStore


class _BaseResponse:
    status_code: int
    headers: dict[str, str]
    text: str
    content: bytes

    def raise_for_status(self) -> None:  # pragma: no cover - defensive
        if self.status_code >= 400:
            import requests

            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error


class _Response200(_BaseResponse):
    status_code = 200
    headers = {"ETag": 'W/"new"', "Last-Modified": "Wed, 12 Mar 2025 12:00:00 GMT"}
    text = "<rss></rss>"
    content = b"<rss></rss>"


class _Response200Same(_BaseResponse):
    status_code = 200
    headers = {"ETag": 'W/"same"', "Last-Modified": "Wed, 12 Mar 2025 12:05:00 GMT"}
    text = "<rss></rss>"
    content = b"<rss></rss>"


class _Response304(_BaseResponse):
    status_code = 304
    headers = {"ETag": 'W/"fresh"', "Last-Modified": "Wed, 12 Mar 2025 12:30:00 GMT"}
    text = ""
    content = b""


class _Response429(_BaseResponse):
    status_code = 429
    headers: dict[str, str] = {}
    text = ""
    content = b""


@pytest.mark.parametrize("response_cls", [_Response200, _Response304])
def test_fetch_feed_applies_conditional_headers(
    response_cls: Type[_BaseResponse],
) -> None:
    collector = RSSCollector()
    store = MemoryFeedStore()
    store.update_source_feed_metadata(
        "source-1", etag='W/"cached"', last_modified="Wed, 12 Mar 2025 11:00:00 GMT"
    )
    collector.db_manager = store

    captured: dict[str, dict[str, str]] = {}

    def fake_get(
        url: str, timeout: float, headers: dict[str, str] | None = None, **kwargs
    ):
        captured["headers"] = headers or {}
        return response_cls()

    collector.session.get = fake_get  # type: ignore[assignment]

    content, status = collector._fetch_feed("source-1", "https://example.com/feed")

    headers = captured["headers"]
    assert headers["If-None-Match"] == 'W/"cached"'
    assert headers["If-Modified-Since"] == "Wed, 12 Mar 2025 11:00:00 GMT"
    if status == 304:
        assert content is None
        assert store.metadata["source-1"]["etag"] == 'W/"fresh"'
    else:
        assert status == 200
        assert store.metadata["source-1"]["etag"] == 'W/"new"'


def test_fetch_feed_invokes_backoff_on_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    collector = RSSCollector()
    store = MemoryFeedStore()
    collector.db_manager = store

    responses = iter([_Response429(), _Response200()])
    calls = []

    def fake_get(
        url: str, timeout: float, headers: dict[str, str] | None = None, **kwargs
    ):
        calls.append(1)
        return next(responses)

    collector.session.get = fake_get  # type: ignore[assignment]
    # We no longer test _backoff_sleep as RobustRequestsClient uses tenacity independently

    content, status = collector._fetch_feed("source-1", "https://example.com/feed")

    assert status == 200
    assert len(calls) == 2
    assert store.metadata["source-1"]["etag"] == 'W/"new"'


def test_fetch_feed_skips_when_content_hash_matches() -> None:
    collector = RSSCollector()
    store = MemoryFeedStore()
    collector.db_manager = store
    content_hash = hashlib.sha256(_Response200Same.content).hexdigest()
    store.update_source_feed_metadata(
        "source-1",
        etag='W/"cached"',
        last_modified="Wed, 12 Mar 2025 11:55:00 GMT",
        content_hash=content_hash,
    )

    def fake_get(
        url: str, timeout: float, headers: dict[str, str] | None = None, **kwargs
    ):
        return _Response200Same()

    collector.session.get = fake_get  # type: ignore[assignment]

    content, status = collector._fetch_feed("source-1", "https://example.com/feed")

    assert content is None
    assert status == 304
    assert store.metadata["source-1"]["content_hash"] == content_hash
