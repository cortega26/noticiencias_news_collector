"""Plan 101 coverage backfill: RSSCollector early-return, fetch/parse helper
and processing branches.

Each test drives one coherent branch with mocked seams (no network, no DB);
together they pin the collector behaviors adjacent to the plan 101 config
threading (RSSCollector(config=...) -> PreScorer(config=...)).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests
from noticiencias.config_manager import load_config

from news_collector.collectors.rss_collector import RSSCollector

SOURCE_ID = "coverage_src"
BASE_CONFIG = {
    "url": "http://example.com/feed.xml",
    "name": "Coverage Source",
    "category": "science",
    "credibility_score": 0.9,
}


@pytest.fixture
def collector():
    with patch("news_collector.collectors.base_collector.get_database_manager"):
        instance = RSSCollector(config=load_config())
    db = MagicMock()
    db.get_source_circuit_state.return_value = None
    db.get_source_feed_metadata.return_value = None
    db.article_exists.return_value = False
    db.articles_exist.return_value = set()
    instance.db_manager = db
    return instance


def _ok_fetch(**overrides):
    payload = {
        "success": True,
        "status_code": 200,
        "content": b"<rss>ok</rss>",
        "url": BASE_CONFIG["url"],
    }
    payload.update(overrides)
    return payload


def _response(status=200, content=b"<rss>ok</rss>", headers=None):
    resp = MagicMock()
    resp.status_code = status
    resp.content = content
    resp.headers = headers or {}
    resp.encoding = "utf-8"
    return resp


# --- collect_from_source early returns -------------------------------------


def test_blocked_source_short_circuits(collector):
    with patch.object(
        collector, "_fetch_feed_robust", side_effect=AssertionError("no fetch")
    ):
        stats = collector.collect_from_source(
            SOURCE_ID, {**BASE_CONFIG, "status": "blocked"}
        )
    assert stats["success"] is True
    assert stats["error_message"] == "Source blocked in config"


def test_circuit_cooldown_skips_fetch(collector):
    collector.db_manager.get_source_circuit_state.return_value = {
        "status": "COOLDOWN",
        "next_retry_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    with patch.object(
        collector, "_fetch_feed_robust", side_effect=AssertionError("no fetch")
    ):
        stats = collector.collect_from_source(SOURCE_ID, dict(BASE_CONFIG))
    assert stats["success"] is True
    assert "Cooldown" in stats["error_message"]


def test_duplicate_job_skips_fetch(collector):
    key = collector._make_job_key(SOURCE_ID, BASE_CONFIG["url"])
    collector._register_job(key)
    with patch.object(
        collector, "_fetch_feed_robust", side_effect=AssertionError("no fetch")
    ):
        stats = collector.collect_from_source(SOURCE_ID, dict(BASE_CONFIG))
    assert stats["success"] is True


def test_robots_disallowed_sends_to_dlq(collector):
    with (
        patch.object(collector, "_respect_robots", return_value=(False, 0.0)),
        patch.object(collector, "_send_to_dlq") as dlq,
    ):
        stats = collector.collect_from_source(SOURCE_ID, dict(BASE_CONFIG))
    assert stats["success"] is False
    assert stats["error_message"] == "Bloqueado por robots.txt"
    dlq.assert_called_once()


def test_article_process_error_counted(collector):
    with (
        patch.object(collector, "_fetch_feed_robust", return_value=_ok_fetch()),
        patch.object(
            collector,
            "_parse_feed_robust",
            return_value={"success": True, "parsed_feed": MagicMock()},
        ),
        patch.object(
            collector,
            "_extract_articles_from_feed",
            return_value=[{"url": "http://example.com/a"}],
        ),
        patch.object(collector, "_process_article", side_effect=RuntimeError("boom")),
        patch.object(collector, "_filter_and_save_articles", return_value=0),
    ):
        stats = collector.collect_from_source(SOURCE_ID, dict(BASE_CONFIG))
    assert stats["success"] is True
    assert collector.session_stats["errors_encountered"] == 1


def test_network_error_records_tracker_failure():
    with patch("news_collector.collectors.base_collector.get_database_manager"):
        instance = RSSCollector(config=load_config(), health_tracker=MagicMock())
    instance.db_manager = MagicMock()
    instance.db_manager.get_source_circuit_state.return_value = None
    with patch.object(
        instance,
        "_fetch_feed_robust",
        side_effect=requests.RequestException("down"),
    ):
        stats = instance.collect_from_source(SOURCE_ID, dict(BASE_CONFIG))
    assert stats["success"] is False
    assert "red general" in stats["error_message"]
    instance.health_tracker.record_failure.assert_called_once()


def test_unexpected_error_is_contained(collector):
    with patch.object(collector, "_fetch_feed_robust", side_effect=ValueError("weird")):
        stats = collector.collect_from_source(SOURCE_ID, dict(BASE_CONFIG))
    assert stats["success"] is False
    assert "inesperado" in stats["error_message"]


def test_circuit_state_update_failure_logged(collector):
    collector.db_manager.update_source_circuit_state.side_effect = RuntimeError(
        "db gone"
    )
    with (
        patch.object(collector, "_fetch_feed_robust", return_value=_ok_fetch()),
        patch.object(
            collector,
            "_parse_feed_robust",
            return_value={"success": True, "parsed_feed": MagicMock()},
        ),
        patch.object(collector, "_extract_articles_from_feed", return_value=[]),
    ):
        stats = collector.collect_from_source(SOURCE_ID, dict(BASE_CONFIG))
    assert stats["success"] is True  # update failure must not fail collection


# --- _fetch_feed / _fetch_feed_robust helpers -------------------------------


def test_fetch_feed_decode_fallback(collector):
    with patch.object(
        collector,
        "_fetch_feed_robust",
        return_value={"content": b"\xff\xfe", "status_code": 200, "encoding": "ascii"},
    ):
        text, status = collector._fetch_feed(SOURCE_ID, BASE_CONFIG["url"])
    assert status == 200
    assert text == b"\xff\xfe".decode("utf-8", errors="replace")


def test_fetch_robust_metadata_failure_is_debug_logged(collector):
    collector.db_manager.get_source_feed_metadata.side_effect = RuntimeError("db")
    collector.client = MagicMock()
    collector.client.get.return_value = _response()
    result = collector._fetch_feed_robust(SOURCE_ID, dict(BASE_CONFIG))
    assert result["success"] is True


def test_fetch_robust_merges_custom_headers(collector):
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen.update(headers or {})
        return _response()

    collector.client = MagicMock()
    collector.client.get.side_effect = fake_get
    result = collector._fetch_feed_robust(
        SOURCE_ID, {**BASE_CONFIG, "headers": {"X-Custom": "yes"}}
    )
    assert result["success"] is True
    assert seen.get("X-Custom") == "yes"


def test_fetch_robust_304_metadata_failure_tolerated(collector):
    collector.db_manager.update_source_feed_metadata.side_effect = RuntimeError("db")
    collector.client = MagicMock()
    collector.client.get.return_value = _response(status=304, content=b"")
    result = collector._fetch_feed_robust(SOURCE_ID, dict(BASE_CONFIG))
    assert result["success"] is True
    assert result["status_code"] == 304


def test_fetch_robust_content_unchanged_metadata_failure_tolerated(collector):
    content = b"<rss>same</rss>"
    digest = hashlib.sha256(content).hexdigest()
    collector.db_manager.get_source_feed_metadata.return_value = {
        "content_hash": digest,
        "etag": None,
        "last_modified": None,
    }
    collector.db_manager.update_source_feed_metadata.side_effect = RuntimeError("db")
    collector.client = MagicMock()
    collector.client.get.return_value = _response(content=content)
    result = collector._fetch_feed_robust(SOURCE_ID, dict(BASE_CONFIG))
    assert result["success"] is True
    assert result["status_code"] == 304


def test_fetch_robust_save_metadata_failure_tolerated(collector):
    collector.db_manager.update_source_feed_metadata.side_effect = RuntimeError("db")
    collector.client = MagicMock()
    collector.client.get.return_value = _response(content=b"<rss>fresh</rss>")
    result = collector._fetch_feed_robust(SOURCE_ID, dict(BASE_CONFIG))
    assert result["success"] is True
    assert result["content"] == b"<rss>fresh</rss>"


def test_fetch_robust_rejects_oversize_feed(collector):
    collector.client = MagicMock()
    collector.client.get.return_value = _response(content=b"x" * (10 * 1024 * 1024 + 1))
    result = collector._fetch_feed_robust(SOURCE_ID, dict(BASE_CONFIG))
    assert result["success"] is False
    assert "10MB" in result["error_message"]


def _scrapling_page(status=200, body=b"<rss>waf</rss>"):
    return SimpleNamespace(status=status, body=body)


def test_fetch_robust_curl_cffi_success(collector):
    with patch("scrapling.Fetcher.get", return_value=_scrapling_page()):
        result = collector._fetch_feed_robust(
            SOURCE_ID, {**BASE_CONFIG, "use_curl_cffi": True}
        )
    assert result["success"] is True
    assert result["content"] == b"<rss>waf</rss>"


def test_fetch_robust_curl_cffi_http_error(collector):
    with patch("scrapling.Fetcher.get", return_value=_scrapling_page(status=503)):
        result = collector._fetch_feed_robust(
            SOURCE_ID, {**BASE_CONFIG, "use_curl_cffi": True}
        )
    assert result["success"] is False
    assert "503" in result["error_message"]


def test_fetch_robust_curl_cffi_oversize(collector):
    with patch(
        "scrapling.Fetcher.get",
        return_value=_scrapling_page(body=b"x" * (10 * 1024 * 1024 + 1)),
    ):
        result = collector._fetch_feed_robust(
            SOURCE_ID, {**BASE_CONFIG, "use_curl_cffi": True}
        )
    assert result["success"] is False
    assert "10MB" in result["error_message"]


def test_fetch_robust_curl_cffi_exception(collector):
    with patch("scrapling.Fetcher.get", side_effect=RuntimeError("waf blocked")):
        result = collector._fetch_feed_robust(
            SOURCE_ID, {**BASE_CONFIG, "use_curl_cffi": True}
        )
    assert result["success"] is False
    assert "curl_cffi" in result["error_message"]


# --- extraction / prescorer / image branches --------------------------------


def _candidate(idx, summary_len=20):
    return {
        "url": f"http://example.com/a{idx}",
        "title": f"Candidate {idx} with a sufficiently long title",
        "summary": "s" * summary_len,
        "published_date": datetime.now(timezone.utc),
    }


def _extract(collector, candidates, **router_overrides):
    from news_collector.config.settings import get_runtime_config

    max_articles = get_runtime_config().collection_config["max_articles_per_source"]
    route = {
        "content": "C" * 100,
        "raw_content": "",
        "strategy_used": "none",
        "success": True,
    }
    route.update(router_overrides)
    with (
        patch.object(collector.parser, "extract_items", return_value=candidates),
        patch.object(
            collector.router,
            "route_enrichment",
            return_value=route,
        ),
    ):
        return (
            collector._extract_articles_from_feed(
                MagicMock(), dict(BASE_CONFIG), SOURCE_ID
            ),
            max_articles,
        )


def test_extract_stops_at_fetch_limit(collector):
    from news_collector.config.settings import get_runtime_config

    cfg = get_runtime_config()
    limit = cfg.collection_config["max_articles_per_source"] * 4
    candidates = [_candidate(i) for i in range(limit + 5)]
    with patch.object(
        collector.pre_scorer, "select_top_candidates", side_effect=lambda c, **k: c
    ):
        articles, _ = _extract(collector, candidates)
    # Without the break the loop would keep all limit + 5 candidates.
    assert len(articles) == limit


def test_extract_skips_known_urls(collector):
    # Plan 092 switched the duplicate filter to the bulk API, which returns
    # canonicalized URLs — the fake mirrors that contract.
    from news_collector.utils.url_canonicalizer import canonicalize_url

    collector.db_manager.articles_exist.side_effect = lambda urls: {
        canonicalize_url(u) or u for u in urls if u.endswith("/a0")
    }
    articles, _ = _extract(collector, [_candidate(0), _candidate(1)])
    assert [a["url"] for a in articles] == ["http://example.com/a1"]


def test_extract_heuristic_fallback_sorts_by_summary(collector):
    from news_collector.config.settings import get_runtime_config

    max_articles = get_runtime_config().collection_config["max_articles_per_source"]
    candidates = [_candidate(i, summary_len=10 + i) for i in range(max_articles + 2)]
    with patch.object(collector.pre_scorer, "model_name", "ollama"):
        articles, _ = _extract(collector, candidates)
    assert len(articles) == max_articles
    lengths = [len(a.get("summary", "")) for a in articles]
    assert lengths == sorted(lengths, reverse=True)


def test_extract_llm_ranking_path(collector):
    from news_collector.config.settings import get_runtime_config

    max_articles = get_runtime_config().collection_config["max_articles_per_source"]
    candidates = [_candidate(i) for i in range(max_articles + 2)]
    with (
        patch.object(collector.pre_scorer, "model_name", "test-llm"),
        patch.object(
            collector.pre_scorer,
            "select_top_candidates",
            return_value=candidates[:max_articles],
        ) as rank,
    ):
        articles, _ = _extract(collector, candidates)
    assert len(articles) == max_articles
    rank.assert_called_once()


def test_extract_accepts_valid_feed_image(collector):
    with patch.object(collector.image_extractor, "validate_image", return_value=True):
        articles, _ = _extract(
            collector, [{**_candidate(0), "image_url": "http://example.com/i.jpg"}]
        )
    assert articles[0]["_image_status"] == "IMAGE_OK"
    assert articles[0]["_image_source"] == "feed"


def test_extract_rejects_invalid_feed_image(collector):
    with patch.object(collector.image_extractor, "validate_image", return_value=False):
        articles, _ = _extract(
            collector, [{**_candidate(0), "image_url": "http://example.com/i.jpg"}]
        )
    assert articles[0].get("image_url") in (None, "http://example.com/i.jpg")
    assert articles[0]["_image_status"] != "IMAGE_OK"


def test_extract_router_error_skips_candidate(collector):
    with (
        patch.object(collector.parser, "extract_items", return_value=[_candidate(0)]),
        patch.object(
            collector.router, "route_enrichment", side_effect=RuntimeError("router")
        ),
    ):
        articles = collector._extract_articles_from_feed(
            MagicMock(), dict(BASE_CONFIG), SOURCE_ID
        )
    assert articles == []


# --- _process_article branches ----------------------------------------------


def _raw_article(**overrides):
    article = {
        "url": "http://example.com/processed",
        "title": "A sufficiently long title for validation purposes",
        "summary": "Summary text. " * 10,
        "content": "Content text. " * 100,
        "published_date": datetime.now(timezone.utc),
        "authors": ["Real Person"],
        "source_metadata": {},
    }
    article.update(overrides)
    return article


def test_process_article_missing_identity_returns_none(collector):
    assert (
        collector._process_article({"title": ""}, SOURCE_ID, dict(BASE_CONFIG)) is None
    )


def test_process_article_records_doi(collector):
    with patch(
        "news_collector.collectors.rss_collector.enrichment_pipeline"
    ) as pipeline:
        pipeline.enrich_article.return_value = {}
        model = collector._process_article(
            _raw_article(source_metadata={"doi": "10.1234/abc"}),
            SOURCE_ID,
            dict(BASE_CONFIG),
        )
    assert model is not None and model.doi == "10.1234/abc"


def test_process_article_scholarly_failure_falls_back(monkeypatch, collector):
    from news_collector.config import settings as config_settings

    real_cfg = config_settings.get_runtime_config()

    class FakeCfg:
        collection_config = {
            **real_cfg.collection_config,
            "sources": {SOURCE_ID: {"enrichment_strategy": "scholarly_metadata"}},
        }

    monkeypatch.setattr(
        "news_collector.collectors.rss_collector.get_runtime_config",
        lambda: FakeCfg(),
    )
    with patch.object(
        collector.scholarly_enricher,
        "enrich_url",
        return_value={"success": False, "reason": "nope"},
    ):
        model = collector._process_article(_raw_article(), SOURCE_ID, dict(BASE_CONFIG))
    assert model is not None
    assert model.article_metadata.enrichment.model_version == "scholarly_failed"


def test_process_article_enrichment_overrides_language(collector):
    """A schema-valid enrichment payload may override the detected language."""
    with patch(
        "news_collector.collectors.rss_collector.enrichment_pipeline"
    ) as pipeline:
        pipeline.enrich_article.return_value = {
            "language": "es",
            "normalized_title": "Titulo normalizado",
            "normalized_summary": "Resumen normalizado",
            "entities": [],
            "topics": [],
            "sentiment": "neutral",
            "model_version": "test_v1",
        }
        model = collector._process_article(_raw_article(), SOURCE_ID, dict(BASE_CONFIG))
    assert model is not None
    assert model.language == "es"


def test_process_article_validation_failure_goes_to_dlq(collector):
    with (
        patch(
            "news_collector.collectors.rss_collector.enrichment_pipeline"
        ) as pipeline,
        patch.object(collector, "_send_to_dlq") as dlq,
    ):
        pipeline.enrich_article.return_value = {}
        model = collector._process_article(
            _raw_article(title="Hi"), SOURCE_ID, dict(BASE_CONFIG)
        )
    assert model is None
    dlq.assert_called_once()
    assert dlq.call_args.args[2] == "collector_payload_invalid"


# --- trivial seams ------------------------------------------------------------


def test_fetch_feed_content_delegates_to_client(collector):
    sentinel = MagicMock()
    collector.client = MagicMock()
    collector.client.get.return_value = sentinel
    assert collector._fetch_feed_content("http://example.com/f", {"A": "b"}) is sentinel
    collector.client.get.assert_called_once_with(
        "http://example.com/f", headers={"A": "b"}
    )


def test_replay_source_setter_and_session_stats(collector):
    collector.set_feed_replay_source(object())
    assert collector._feed_replay_source is not None
    collector._create_session()  # deprecated no-op shim
    stats = collector.get_session_stats()
    assert stats["sources_checked"] == 0
    assert "session_duration_minutes" in stats
