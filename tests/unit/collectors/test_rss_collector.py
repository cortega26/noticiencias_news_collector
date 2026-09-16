from unittest.mock import MagicMock, patch

import pytest
from noticiencias.config_manager import load_config

from news_collector.collectors.rss_collector import RSSCollector


@pytest.fixture
def rss_collector():
    with patch("news_collector.collectors.base_collector.get_database_manager"):
        logger_mock = MagicMock()
        return RSSCollector(logger_factory=logger_mock, config=load_config())


from datetime import datetime


def test_parse_feed_entry(rss_collector):
    # RSSCollector delegates to parser. Test that integration or skip if unit testing parser separately.
    # We can check if _process_article works, which uses the dict.
    raw_article = {
        "title": "Title That Is Long Enough (>10 chars)",
        "url": "http://test.com",
        "summary": "Summary",
        "content": "Content " * 200,  # > 1000 chars
        "published_date": datetime(2025, 1, 1, 12, 0, 0),
    }
    enrichment_mock = {
        "language": "en",
        "topics": ["Science"],
        "sentiment": "neutral",
        "entities": [],
        "normalized_title": "Title",
        "normalized_summary": "Summary",
        "model_version": "v1",
    }
    with patch(
        "news_collector.collectors.rss_collector.enrichment_pipeline.enrich_article",
        return_value=enrichment_mock,
    ):
        processed = rss_collector._process_article(
            raw_article,
            "s1",
            {
                "name": "Src",
                "category": "general",
                "credibility_score": 1.0,
                "language": "en",
            },
        )
    assert processed is not None
    assert processed.title == "Title That Is Long Enough (>10 chars)"


def test_collect_sync_mock(rss_collector):
    with patch(
        "news_collector.collectors.rss_collector.feedparser.parse"
    ) as mock_parse:
        mock_parse.return_value.entries = []
        mock_parse.return_value.bozo = False

    with (
        patch("news_collector.collectors.rss_collector.feedparser.parse") as mock_parse,
        patch.object(
            rss_collector,
            "_fetch_feed_robust",
            return_value={
                "success": True,
                "status_code": 200,
                "content": b"xml-content",
                "url": "http://feed.com",
            },
        ),
    ):

        mock_parse.return_value.entries = []
        mock_parse.return_value.bozo = False

        articles = rss_collector.collect_from_source(
            "s1", {"url": "http://feed.com", "name": "RSS"}
        )
        assert isinstance(articles, dict)
        mock_parse.assert_called_with(b"xml-content")


def test_extract_articles_recency_filter_skips_non_datetime(rss_collector):
    """The recency filter must not crash when a candidate carries a
    non-datetime published_date (e.g. a string from a future source), and
    must drop candidates older than the recency window."""
    from datetime import timedelta, timezone

    recent = datetime.now(timezone.utc)
    old = recent - timedelta(days=400)
    candidates = [
        {
            "title": "Old article title that is long enough",
            "url": "https://old.example.com/a",
            "published_date": old,
            "summary": "s" * 60,
        },
        {
            "title": "Fresh article title that is long enough",
            "url": "https://fresh.example.com/b",
            "published_date": recent,
            "summary": "s" * 60,
        },
        {
            "title": "String-date article title that is long enough",
            "url": "https://str.example.com/c",
            "published_date": "2024-01-01T00:00:00Z",
            "summary": "s" * 60,
        },
    ]

    parser_mock = MagicMock()
    parser_mock.extract_items.return_value = candidates
    rss_collector.parser = parser_mock
    rss_collector.db_manager = MagicMock()
    rss_collector.db_manager.article_exists.return_value = False
    rss_collector.pre_scorer = MagicMock()
    rss_collector.pre_scorer.model_name = "ollama"

    from unittest.mock import patch as _patch

    with (
        _patch.object(
            rss_collector, "_process_article", return_value=None
        ) as mock_process,
        _patch.object(rss_collector, "router", MagicMock()),
        _patch.object(rss_collector, "image_extractor", MagicMock()),
    ):
        # Only the date filter path runs here; deep processing is stubbed.
        from news_collector.config.settings import refresh_runtime_config

        refresh_runtime_config()
        raw_articles = rss_collector._extract_articles_from_feed(
            MagicMock(), {"url": "http://feed.com"}, "s1"
        )
        urls = [a["url"] for a in raw_articles]
        # Old item dropped by the recency gate; fresh + string-date kept
        # (string date is not compared, so it passes rather than crashing).
        assert "https://old.example.com/a" not in urls
        assert "https://fresh.example.com/b" in urls
        assert "https://str.example.com/c" in urls


def test_parse_success_records_article_count_as_found(rss_collector):
    """FOUND column must count parsed articles, not the implicit count-1
    (regression for the FOUND/SAVED mislabeling, plans ledger #248)."""
    from news_collector.diagnostics import SourceHealthTracker

    tracker = SourceHealthTracker()
    candidates = [
        {
            "title": f"Title {i} is long enough",
            "url": f"http://feed.com/{i}",
            "summary": "Summary",
            "published_date": datetime(2026, 8, 1, 12, 0, 0),
        }
        for i in range(3)
    ]

    with (
        patch.object(
            rss_collector,
            "_fetch_feed_robust",
            return_value={
                "success": True,
                "status_code": 200,
                "content": b"xml-content",
                "url": "http://feed.com",
            },
        ),
        patch.object(
            rss_collector,
            "_parse_feed_robust",
            return_value={"success": True, "parsed_feed": object()},
        ),
        patch.object(rss_collector.parser, "extract_items", return_value=candidates),
        # The router must not reach the network: this test only asserts the
        # FOUND/parse count, not enrichment behavior (real HTTP to feed.com
        # made this order-dependent under pytest-randomly).
        patch.object(
            rss_collector,
            "router",
            MagicMock(route_enrichment=lambda *a, **k: {}),
        ),
    ):
        rss_collector.health_tracker = tracker
        rss_collector.db_manager.article_exists.return_value = False
        rss_collector.collect_from_source(
            "s1", {"url": "http://feed.com", "name": "RSS"}
        )

    source = tracker.get_source("s1")
    assert source.parsed_ok == 3


class _BatchOnlyDbManager:
    """Fake db_manager pinning the bulk dedup path.

    The singular per-item check raises if touched; the bulk check returns
    a fixed set and records its calls.
    """

    def __init__(self, existing_urls):
        self._existing = set(existing_urls)
        self.bulk_calls = []

    def article_exists(self, url):  # pragma: no cover - tripwire
        raise AssertionError("per-item article_exists must not be called")

    def articles_exist(self, urls):
        self.bulk_calls.append(list(urls))
        return set(self._existing)


def _recent_candidate(url, summary="s" * 60):
    from datetime import timezone

    return {
        "title": f"Article title for {url} that is long enough",
        "url": url,
        "published_date": datetime.now(timezone.utc),
        "summary": summary,
    }


def _run_extraction(rss_collector, candidates, db_manager):
    """Run _extract_articles_from_feed with network-touching seams stubbed."""
    from unittest.mock import patch as _patch

    from news_collector.config.settings import refresh_runtime_config

    parser_mock = MagicMock()
    parser_mock.extract_items.return_value = candidates
    rss_collector.parser = parser_mock
    rss_collector.db_manager = db_manager
    rss_collector.pre_scorer = MagicMock()
    rss_collector.pre_scorer.model_name = "ollama"
    with (
        _patch.object(
            rss_collector, "router", MagicMock(route_enrichment=lambda *a, **k: {})
        ),
        _patch.object(rss_collector, "image_extractor", MagicMock()),
    ):
        refresh_runtime_config()
        return rss_collector._extract_articles_from_feed(
            MagicMock(), {"url": "http://feed.com"}, "s1"
        )


def test_extract_articles_batches_duplicate_check_single_bulk_call(rss_collector):
    """Duplicate filtering must issue ONE bulk articles_exist call and never
    the per-item article_exists (plan 092 regression)."""
    urls = [f"https://batch.example.com/n{i}" for i in range(6)]
    existing = {urls[1], urls[4]}
    db_manager = _BatchOnlyDbManager(existing)

    articles = _run_extraction(
        rss_collector, [_recent_candidate(u) for u in urls], db_manager
    )

    assert db_manager.bulk_calls == [urls]  # one call, order preserved
    assert [a["url"] for a in articles] == [urls[0], urls[2], urls[3], urls[5]]


def test_extract_articles_truncation_matches_fetch_limit_semantics(rss_collector):
    """Order + fetch_limit truncation must match the old per-item loop:
    duplicates interspersed, loop keeps the first fetch_limit survivors."""
    from news_collector.config.settings import get_runtime_config

    cfg = get_runtime_config()
    max_articles = cfg.collection_config["max_articles_per_source"]
    fetch_limit = max_articles * 4

    total = fetch_limit + 5
    urls = [f"https://batch.example.com/t{i}" for i in range(total)]
    dupes = {0, 10, total - 1}
    existing = {urls[i] for i in dupes}
    db_manager = _BatchOnlyDbManager(existing)

    articles = _run_extraction(
        rss_collector, [_recent_candidate(u) for u in urls], db_manager
    )

    # Old loop semantics: skip dupes, keep the first `fetch_limit` new
    # candidates in feed order (count only increments on keep).
    expected_kept = [u for i, u in enumerate(urls) if i not in dupes][:fetch_limit]
    assert db_manager.bulk_calls == [urls]  # still exactly one bulk call
    # Equal-length summaries keep the heuristic pre-scorer sort stable, so
    # the first `max_articles` survivors come back in feed order.
    assert [a["url"] for a in articles] == expected_kept[:max_articles]
    # Late new candidates past the fetch_limit window never make it.
    assert urls[total - 2] not in [a["url"] for a in articles]


def test_extract_articles_bulk_match_uses_canonicalized_urls(rss_collector):
    """A candidate whose raw URL differs from the stored canonical form
    (case-only here) must still count as a duplicate — the same
    canonicalization the singular check applied (plan 092 parity)."""
    from news_collector.utils.url_canonicalizer import canonicalize_url

    raw_dupe = "https://EXAMPLE.com/case-dupe"
    canonical_dupe = canonicalize_url(raw_dupe) or raw_dupe
    assert canonical_dupe != raw_dupe  # guard: the case must be meaningful
    # The singular check canonicalized too, so it agreed on this duplicate.
    assert canonical_dupe == "https://example.com/case-dupe"

    urls = [
        "https://batch.example.com/fresh-a",
        raw_dupe,
        "https://batch.example.com/fresh-b",
    ]
    db_manager = _BatchOnlyDbManager({canonical_dupe})

    articles = _run_extraction(
        rss_collector, [_recent_candidate(u) for u in urls], db_manager
    )

    assert [a["url"] for a in articles] == [
        "https://batch.example.com/fresh-a",
        "https://batch.example.com/fresh-b",
    ]
