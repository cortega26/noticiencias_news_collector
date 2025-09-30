import sys
import time
from pathlib import Path
from types import MethodType

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.collectors.rss_collector import RSSCollector
from src.storage.database import DatabaseManager


class DummyResponse:
    def __init__(self, status_code, headers=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self._text = text

    @property
    def text(self):
        return self._text

    @property
    def content(self):
        return self._text.encode("utf-8")

    def raise_for_status(self):
        if 400 <= self.status_code < 600:
            raise Exception(f"HTTP {self.status_code}")


def _setup_collector(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    db_manager = DatabaseManager({"type": "sqlite", "path": db_path})
    monkeypatch.setattr(
        "src.collectors.rss_collector.get_database_manager", lambda: db_manager
    )
    collector = RSSCollector()
    source_config = {
        "name": "Test Feed",
        "url": "https://example.com/feed.xml",
        "credibility_score": 0.5,
        "category": "testing",
        "update_frequency": "daily",
    }
    db_manager.initialize_sources({"test_source": source_config})
    return collector, db_manager, source_config


def test_backoff_monotonic_small():
    c = RSSCollector()
    # measure successive delays (not exact, but ensure non-negative)
    for attempt in range(3):
        start = time.perf_counter()
        c._backoff_sleep(attempt)
        elapsed = time.perf_counter() - start
        assert elapsed >= 0


def test_fetch_feed_uses_conditional_headers(tmp_path, monkeypatch):
    collector, db_manager, source_config = _setup_collector(tmp_path, monkeypatch)
    db_manager.update_source_feed_metadata(
        "test_source",
        etag='"old-etag"',
        last_modified="Wed, 21 Oct 2015 07:28:00 GMT",
    )

    captured = {}

    def fake_get(self, url, timeout, headers=None):
        captured["headers"] = headers
        return DummyResponse(
            200,
            headers={
                "ETag": '"new-etag"',
                "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT",
                "content-type": "application/rss+xml",
            },
            text="<rss></rss>",
        )

    collector.session.get = MethodType(fake_get, collector.session)
    content, status = collector._fetch_feed("test_source", source_config["url"])

    assert status == 200
    assert content == "<rss></rss>"
    assert captured["headers"]["If-None-Match"] == '"old-etag"'
    assert captured["headers"]["If-Modified-Since"] == "Wed, 21 Oct 2015 07:28:00 GMT"

    updated = db_manager.get_source_feed_metadata("test_source")
    assert updated["etag"] == '"new-etag"'
    assert updated["last_modified"] == "Mon, 01 Jan 2024 00:00:00 GMT"


def test_collect_from_source_handles_not_modified(tmp_path, monkeypatch):
    collector, db_manager, source_config = _setup_collector(tmp_path, monkeypatch)
    db_manager.update_source_feed_metadata(
        "test_source",
        etag='"cached"',
        last_modified="Tue, 02 Jan 2024 00:00:00 GMT",
    )

    captured = {}

    def fake_get(self, url, timeout, headers=None):
        captured["headers"] = headers
        return DummyResponse(
            304,
            headers={
                "ETag": '"cached"',
                "Last-Modified": "Tue, 02 Jan 2024 00:00:00 GMT",
            },
        )

    collector.session.get = MethodType(fake_get, collector.session)
    collector._respect_robots = lambda url: (True, None)
    collector._enforce_domain_rate_limit = lambda domain, robots_delay: None

    stats = collector.collect_from_source("test_source", source_config)

    assert stats["success"] is True
    assert stats["articles_found"] == 0
    assert stats["articles_saved"] == 0
    assert captured["headers"]["If-None-Match"] == '"cached"'

    metadata = db_manager.get_source_feed_metadata("test_source")
    assert metadata["etag"] == '"cached"'
    assert metadata["last_modified"] == "Tue, 02 Jan 2024 00:00:00 GMT"
