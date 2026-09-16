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


# --- Step 3b (plan 092): characterization backfill ---------------------------
# Pin CURRENT behavior with fakes only (no network, no timers). If any of
# these pin something that looks buggy, that is a report — not a fix — per
# the plan's TESTS-ONLY rule.


def _hermetic_collect(rss_collector, fetch_result=None, fetch_error=None):
    """Drive collect_from_source with all I/O seams stubbed.

    Robots/rate-limit/fetch are faked, so no network and no real sleeps.
    """
    from unittest.mock import patch as _patch

    rss_collector.db_manager.get_source_circuit_state.return_value = None
    fetch_mock = MagicMock(side_effect=fetch_error, return_value=fetch_result)
    with (
        _patch.object(rss_collector, "_respect_robots", return_value=(True, 0.0)),
        _patch.object(rss_collector, "_enforce_domain_rate_limit", return_value=None),
        _patch.object(rss_collector, "_fetch_feed_robust", fetch_mock),
    ):
        stats = rss_collector.collect_from_source(
            "s1", {"url": "http://feed.com", "name": "Src"}
        )
    return stats, fetch_mock


def test_collect_circuit_naive_datetime_treated_as_utc(rss_collector):
    """A naive SQLite-style next_retry_at is assumed UTC (not skipped, not
    crashed) — pins the tz-awareness normalization branch."""
    from datetime import timedelta, timezone

    naive_future = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(
        tzinfo=None
    )
    rss_collector.db_manager.get_source_circuit_state.return_value = {
        "status": "COOLDOWN",
        "next_retry_at": naive_future,
    }
    with patch.object(
        rss_collector, "_fetch_feed_robust", side_effect=AssertionError("no fetch")
    ):
        stats = rss_collector.collect_from_source(
            "s1", {"url": "http://feed.com", "name": "Src"}
        )
    assert stats["success"] is True
    assert "Cooldown" in stats["error_message"]


def test_collect_unexpected_error_records_tracker_failure(rss_collector):
    """A non-network exception inside collection is contained AND reported
    to the health tracker (pins the generic-handler tracker branch)."""
    rss_collector.health_tracker = MagicMock()
    stats, _ = _hermetic_collect(rss_collector, fetch_error=ValueError("weird"))
    assert stats["success"] is False
    assert "inesperado" in stats["error_message"]
    rss_collector.health_tracker.record_failure.assert_called_once()
    assert (
        rss_collector.health_tracker.record_failure.call_args.args[2]
        == "unexpected_error"
    )


def test_collect_network_error_without_tracker_skips_record(rss_collector):
    """Without a health tracker a network error is still contained; the
    record_failure branch is simply skipped (pins the tracker-absent edge)."""
    import requests

    assert rss_collector.health_tracker is None
    stats, _ = _hermetic_collect(
        rss_collector, fetch_error=requests.RequestException("down")
    )
    assert stats["success"] is False
    assert "red general" in stats["error_message"]


def test_collect_circuit_kill_switch_bypasses_cooldown(rss_collector, monkeypatch):
    """ENABLE_CIRCUIT_BREAKER=false skips the cooldown gate: a COOLDOWN
    source is still fetched (pins the kill-switch bypass edge)."""
    from datetime import timedelta, timezone

    monkeypatch.setenv("ENABLE_CIRCUIT_BREAKER", "false")
    rss_collector.db_manager.get_source_circuit_state.return_value = {
        "status": "COOLDOWN",
        "next_retry_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    stats, fetch_mock = _hermetic_collect(
        rss_collector, fetch_result={"success": False, "error_message": "fetch ran"}
    )
    fetch_mock.assert_called_once()  # not skipped by the cooldown gate
    assert stats["success"] is False
    assert stats["error_message"] == "fetch ran"


def test_collect_replay_mode_skips_robots_check(rss_collector):
    """With a replay source set, robots/rate-limit gates are bypassed
    (pins the replay bypass edge)."""
    rss_collector.set_feed_replay_source(object())
    with (
        patch.object(
            rss_collector,
            "_respect_robots",
            side_effect=AssertionError("robots must be skipped in replay"),
        ),
        patch.object(
            rss_collector,
            "_fetch_feed_robust",
            return_value={"success": False, "error_message": "fetch ran"},
        ),
    ):
        stats = rss_collector.collect_from_source(
            "s1", {"url": "http://feed.com", "name": "Src"}
        )
    assert stats["success"] is False
    assert stats["error_message"] == "fetch ran"


def test_fetch_robust_replay_error_contained(rss_collector):
    """A replay source raising inside _fetch_feed_robust is contained as a
    'Replay Error' failure (pins the replay-exception branch)."""
    rss_collector.db_manager.get_source_feed_metadata.return_value = None
    rss_collector.set_feed_replay_source(
        MagicMock(fetch_feed=MagicMock(side_effect=RuntimeError("waf down")))
    )
    result = rss_collector._fetch_feed_robust("s1", {"url": "http://feed.com/x"})
    assert result["success"] is False
    assert "Replay Error" in result["error_message"]


def _run_extraction_full(rss_collector, candidates, db_manager, source_config, route):
    """_extract_articles_from_feed driver with configurable router result."""
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
            rss_collector,
            "router",
            MagicMock(route_enrichment=lambda *a, **k: dict(route)),
        ),
        _patch.object(rss_collector, "image_extractor", MagicMock()),
    ):
        refresh_runtime_config()
        return rss_collector._extract_articles_from_feed(
            MagicMock(), dict(source_config), "s1"
        )


def test_extract_image_loop_tries_next_candidate(rss_collector):
    """Image validation keeps iterating past a rejected candidate and takes
    the first valid one (pins the loop-continue edge)."""
    from news_collector.logic.parsers.image_extractor import ImageCandidate

    db_manager = _BatchOnlyDbManager(set())
    route = {
        "content": "C" * 120,
        "raw_content": "<html><body>story</body></html>",
        "strategy_used": "standard",
        "success": True,
    }
    good = ImageCandidate(url="https://img.example.com/good.jpg", source="dom")
    bad = ImageCandidate(url="https://img.example.com/bad.jpg", source="dom")
    with (
        patch.object(
            rss_collector.image_extractor,
            "extract_candidates",
            return_value=[bad, good],
        ),
        patch.object(
            rss_collector.image_extractor, "validate_image", side_effect=[False, True]
        ),
    ):
        # Drive with the REAL image extractor methods patched (not replaced).
        from unittest.mock import patch as _patch

        from news_collector.config.settings import refresh_runtime_config

        parser_mock = MagicMock()
        parser_mock.extract_items.return_value = [
            _recent_candidate("https://loop.example.com/story")
        ]
        rss_collector.parser = parser_mock
        rss_collector.db_manager = db_manager
        rss_collector.pre_scorer = MagicMock()
        rss_collector.pre_scorer.model_name = "ollama"
        with _patch.object(
            rss_collector,
            "router",
            MagicMock(route_enrichment=lambda *a, **k: dict(route)),
        ):
            refresh_runtime_config()
            articles = rss_collector._extract_articles_from_feed(
                MagicMock(), {"url": "http://feed.com"}, "s1"
            )
    assert len(articles) == 1
    assert articles[0]["image_url"] == "https://img.example.com/good.jpg"
    assert articles[0]["_image_status"] == "IMAGE_OK"
    assert articles[0]["_image_source"] == "dom"


def test_extract_preset_article_metadata_preserved(rss_collector):
    """A candidate that already carries article_metadata keeps it (the
    init-defaults branch is skipped — pins the metadata-present edge)."""
    db_manager = _BatchOnlyDbManager(set())
    candidate = _recent_candidate("https://meta.example.com/kept")
    candidate["article_metadata"] = {"preset": True}
    articles = _run_extraction_full(
        rss_collector, [candidate], db_manager, {"url": "http://feed.com"}, {}
    )
    assert len(articles) == 1
    assert articles[0]["article_metadata"]["preset"] is True


def test_extract_summary_only_mode_skips_fallback_stamp(rss_collector):
    """In summary_only content mode a present content is NOT stamped
    summary_fallback (pins the mode-guard edge)."""
    db_manager = _BatchOnlyDbManager(set())
    route = {
        "content": "C" * 120,
        "raw_content": "",
        "strategy_used": "standard",
        "success": True,
    }
    articles = _run_extraction_full(
        rss_collector,
        [_recent_candidate("https://mode.example.com/item")],
        db_manager,
        {"url": "http://feed.com", "content_mode": "summary_only"},
        route,
    )
    assert len(articles) == 1
    assert articles[0].get("content_mode") != "summary_fallback"


def test_extract_empty_content_skips_fallback_stamp(rss_collector):
    """With neither routed content nor summary, the fallback-stamp
    condition short-circuits on empty content (pins the first-operand
    False edge of the mode guard)."""
    db_manager = _BatchOnlyDbManager(set())
    route = {
        "content": "",
        "raw_content": "",
        "strategy_used": "none",
        "success": True,
    }
    articles = _run_extraction_full(
        rss_collector,
        [_recent_candidate("https://empty.example.com/item", summary="")],
        db_manager,
        {"url": "http://feed.com"},
        route,
    )
    assert len(articles) == 1
    assert articles[0].get("content", "") == ""
    assert articles[0].get("content_mode") != "summary_fallback"


def _rich_raw_article(**overrides):
    from datetime import timezone

    article = {
        "url": "http://example.com/characterized",
        "title": "A sufficiently long title for validation purposes",
        "summary": "Summary text. " * 10,
        "content": "Content text. " * 100,
        "published_date": datetime.now(timezone.utc),
        "authors": ["Real Person"],
        "source_metadata": {},
    }
    article.update(overrides)
    return article


def _process_config(rss_collector, source_id="s1"):
    return {
        "name": "Src",
        "category": "general",
        "credibility_score": 1.0,
        "language": "en",
    }


def test_process_article_scholarly_success_rejected_by_schema(
    rss_collector, monkeypatch
):
    """Characterization: a successful scholarly enrichment replaces
    content/title, but its enrichment block lacks the schema-required
    `language` key, so validation fails and the article goes to DLQ.

    This looks like a real bug (success path can never validate), but per
    plan 092's TESTS-ONLY rule it is pinned here and REPORTED, not fixed.
    Pins the scholarly-success branch (1062-1078)."""
    from news_collector.config import settings as config_settings

    real_cfg = config_settings.get_runtime_config()

    class FakeCfg:
        collection_config = {
            **real_cfg.collection_config,
            "sources": {"s1": {"enrichment_strategy": "scholarly_metadata"}},
        }

    monkeypatch.setattr(
        "news_collector.collectors.rss_collector.get_runtime_config",
        lambda: FakeCfg(),
    )
    scholarly_body = "Scholarly body. " * 100
    with (
        patch.object(
            rss_collector.scholarly_enricher,
            "enrich_url",
            return_value={
                "success": True,
                "content": scholarly_body,
                "title": "Scholarly title result",
            },
        ),
        patch.object(rss_collector, "_send_to_dlq") as dlq,
    ):
        model = rss_collector._process_article(
            _rich_raw_article(), "s1", _process_config(rss_collector)
        )
    assert model is None
    dlq.assert_called_once()
    assert dlq.call_args.args[2] == "collector_payload_invalid"


def test_process_article_enrichment_without_language_rejected_by_schema(
    rss_collector,
):
    """Characterization: a truthy enrichment payload WITHOUT a language
    fails validation (`language` is required when the block is present), so
    the article goes to DLQ. Pinned + REPORTED, not fixed (TESTS-ONLY).
    Pins the language-absent edge (1124->1126) with a passing-through run."""
    with (
        patch(
            "news_collector.collectors.rss_collector.enrichment_pipeline"
        ) as pipeline,
        patch.object(rss_collector, "_send_to_dlq") as dlq,
    ):
        pipeline.enrich_article.return_value = {
            "normalized_title": "Titulo",
            "normalized_summary": "Resumen",
            "entities": [],
            "topics": [],
            "sentiment": "neutral",
            "model_version": "test_v1",
        }
        model = rss_collector._process_article(
            _rich_raw_article(), "s1", _process_config(rss_collector)
        )
    assert model is None
    dlq.assert_called_once()
    assert dlq.call_args.args[2] == "collector_payload_invalid"


def test_process_article_enrichment_content_key_rejected_by_schema(rss_collector):
    """Characterization: the code applies `enrichment['content']` when
    present, but the enrichment schema forbids that key, so such payloads
    fail validation and go to DLQ. Pinned + REPORTED, not fixed (TESTS-ONLY).
    Pins the content-application branch (1120-1121)."""
    with (
        patch(
            "news_collector.collectors.rss_collector.enrichment_pipeline"
        ) as pipeline,
        patch.object(rss_collector, "_send_to_dlq") as dlq,
    ):
        pipeline.enrich_article.return_value = {
            "content": "Enriched body. " * 100,
            "normalized_title": "Titulo",
            "normalized_summary": "Resumen",
            "entities": [],
            "topics": [],
            "sentiment": "neutral",
            "model_version": "test_v1",
        }
        model = rss_collector._process_article(
            _rich_raw_article(), "s1", _process_config(rss_collector)
        )
    assert model is None
    dlq.assert_called_once()
    assert dlq.call_args.args[2] == "collector_payload_invalid"


def test_process_article_enrichment_reading_time_key_rejected_by_schema(
    rss_collector,
):
    """Characterization: same as above for `reading_time_minutes` — the code
    applies it (1126-1127) but the schema forbids it in the enrichment block,
    so the article goes to DLQ. Pinned + REPORTED, not fixed (TESTS-ONLY)."""
    with (
        patch(
            "news_collector.collectors.rss_collector.enrichment_pipeline"
        ) as pipeline,
        patch.object(rss_collector, "_send_to_dlq") as dlq,
    ):
        pipeline.enrich_article.return_value = {
            "language": "es",
            "reading_time_minutes": 9,
            "normalized_title": "Titulo",
            "normalized_summary": "Resumen",
            "entities": [],
            "topics": [],
            "sentiment": "neutral",
            "model_version": "test_v1",
        }
        model = rss_collector._process_article(
            _rich_raw_article(), "s1", _process_config(rss_collector)
        )
    assert model is None
    dlq.assert_called_once()
    assert dlq.call_args.args[2] == "collector_payload_invalid"
