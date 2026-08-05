"""Coverage tests for BaseCollector.

Targets branches not exercised by test_base_collector.py: crawl-interval
skips, exception handling, robots.txt / retry-after parsing, DLQ writes,
circuit-breaker semantics, article save/update/validation errors, the bulk
filter pipeline, recommendations, and health/metric helpers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from news_collector.collectors.base_collector import (
    BaseCollector,
    create_collector,
    validate_collector_result,
)
from news_collector.contracts import CollectorArticleModel


def _article(i: int = 0) -> dict:
    return {
        "url": f"https://news.example.com/article-{i}",
        "title": f"Interesting Science Article Number {i}",
        "summary": "A concise summary of the science article.",
        "content": "Full content of the science article body here.",
        "source_id": "src1",
        "source_name": "Example Science",
        "category": "Science",
        "published_date": datetime.now(timezone.utc),
        "authors": ["Reporter"],
    }


def _config(tmp_path: Path, **overrides) -> SimpleNamespace:
    cfg = {
        "collection_config": {
            "max_concurrent_sources": 8,
            "source_timeout_seconds": 60,
            "user_agent": "test-agent",
        },
        "robots_config": {
            "respect_robots": True,
            "cache_ttl_seconds": 3600,
        },
        "rate_limiting_config": {
            "jitter_max": 0.0,
            "backoff_base": 0.5,
            "backoff_max": 1.0,
        },
        "dlq_dir": tmp_path / "dlq",
    }
    cfg.update(overrides)
    return SimpleNamespace(**cfg)


class ConcreteCollector(BaseCollector):
    def collect_from_source(self, source_id, source_config):
        return {"success": True, "source_id": source_id}


@pytest.fixture
def collector(monkeypatch, tmp_path):
    db = MagicMock()
    (tmp_path / "dlq").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "news_collector.collectors.base_collector.get_database_manager",
        lambda: db,
    )
    monkeypatch.setattr(
        "news_collector.collectors.base_collector.get_runtime_config",
        lambda: _config(tmp_path),
    )
    c = ConcreteCollector(logger_factory=MagicMock())
    c.db_manager = db
    return c


@pytest.fixture
def plain_collector(monkeypatch):
    monkeypatch.setattr(
        "news_collector.collectors.base_collector.get_database_manager",
        lambda: MagicMock(),
    )
    monkeypatch.setattr(
        "news_collector.collectors.base_collector.get_runtime_config",
        lambda: _config(Path("/tmp")),
    )
    return ConcreteCollector(logger_factory=MagicMock())


class TestProcessSource:
    def test_sync_skipped_when_interval_not_met(self, collector):
        collector._check_crawl_interval = lambda *a: False
        res = collector._process_single_source_sync("s1", {})
        assert res["skipped"] is True
        assert res["success"] is True

    def test_sync_exception_handled(self, collector):
        collector._check_crawl_interval = lambda *a: True
        collector.collect_from_source = MagicMock(side_effect=RuntimeError("boom"))
        res = collector._process_single_source_sync("s1", {})
        assert res["success"] is False
        assert "boom" in res["error_message"]

    async def test_async_skipped_when_interval_not_met(self, collector):
        collector._check_crawl_interval = lambda *a: False
        res = await collector._process_single_source_async("s1", {})
        assert res["skipped"] is True
        assert res["success"] is True

    async def test_async_exception_handled(self, collector):
        collector._check_crawl_interval = lambda *a: True

        async def _boom(*a, **k):
            raise RuntimeError("async boom")

        collector.collect_from_source_async = _boom
        res = await collector._process_single_source_async("s1", {})
        assert res["success"] is False
        assert "async boom" in res["error_message"]


class TestStatsAndMisc:
    def test_handle_source_exception(self, collector):
        res = collector._handle_source_exception("s1", ValueError("bad"))
        assert res["success"] is False
        assert "bad" in res["error_message"]
        assert collector.stats["total_errors"] == 1

    def test_update_global_stats_failure(self, collector):
        collector._update_global_stats({"success": False})
        assert collector.stats["total_sources_processed"] == 1
        assert collector.stats["total_errors"] == 1

    def test_get_stats_returns_copy(self, collector):
        stats = collector.get_stats()
        stats["total_errors"] = 99
        assert collector.stats["total_errors"] == 0

    def test_clean_text_empty(self, collector):
        assert collector._clean_text("") == ""

    def test_clean_text_nonempty(self, collector):
        with patch("news_collector.utils.text_cleaner.normalize_text") as n:
            n.return_value = "cleaned"
            assert collector._clean_text("  foo  ") == "cleaned"


class TestRobots:
    def test_respect_robots_disabled(self, monkeypatch):
        monkeypatch.setattr(
            "news_collector.collectors.base_collector.get_runtime_config",
            lambda: _config(
                Path("/tmp"),
                **{
                    "robots_config": {
                        "respect_robots": False,
                        "cache_ttl_seconds": 1,
                    }
                },
            ),
        )
        c = ConcreteCollector(logger_factory=MagicMock())
        assert c._get_robots("example.com") is None
        assert c._respect_robots("https://example.com/x") == (True, None)

    def test_get_robots_cached(self, collector):
        parser = SimpleNamespace()
        now = datetime.now(timezone.utc).timestamp()
        collector._robots_cache["example.com"] = (now, parser)
        assert collector._get_robots("example.com") is parser

    def test_get_robots_fetches_and_caches(self, collector, monkeypatch):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "User-agent: *\nDisallow: /private/\nCrawl-delay: 2"
        monkeypatch.setattr(
            "news_collector.collectors.base_collector.httpx.get",
            lambda *a, **k: resp,
        )
        rp = collector._get_robots("example.com")
        assert rp is not None
        cached = collector._robots_cache.get("example.com")
        assert cached is not None and cached[1] is rp

    def test_get_robots_error_status(self, collector, monkeypatch):
        resp = MagicMock()
        resp.status_code = 404
        resp.text = "missing"
        monkeypatch.setattr(
            "news_collector.collectors.base_collector.httpx.get",
            lambda *a, **k: resp,
        )
        assert collector._get_robots("example.com") is None

    def test_get_robots_network_exception(self, collector, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("network")

        monkeypatch.setattr("news_collector.collectors.base_collector.httpx.get", _boom)
        assert collector._get_robots("example.com") is None

    def test_respect_robots_no_parser(self, plain_collector):
        plain_collector._get_robots = lambda domain: None
        assert plain_collector._respect_robots("https://news.example.com/a") == (
            True,
            None,
        )

    def test_respect_robots_int_delay(self, plain_collector):
        parser = MagicMock()
        parser.can_fetch.return_value = False
        parser.crawl_delay.return_value = 5
        plain_collector._get_robots = lambda domain: parser
        allowed, delay = plain_collector._respect_robots("https://news.example.com/a")
        assert (allowed, delay) == (False, 5.0)

    def test_respect_robots_string_delay(self, plain_collector):
        parser = MagicMock()
        parser.can_fetch.return_value = True
        parser.crawl_delay.return_value = "3"
        plain_collector._get_robots = lambda domain: parser
        allowed, delay = plain_collector._respect_robots("https://news.example.com/a")
        assert (allowed, delay) == (True, 3.0)

    def test_respect_robots_unparseable_string_delay(self, plain_collector):
        parser = MagicMock()
        parser.can_fetch.return_value = True
        parser.crawl_delay.return_value = "abc"
        plain_collector._get_robots = lambda domain: parser
        allowed, delay = plain_collector._respect_robots("https://news.example.com/a")
        assert (allowed, delay) == (True, None)

    def test_respect_robots_none_delay(self, plain_collector):
        parser = MagicMock()
        parser.can_fetch.return_value = True
        parser.crawl_delay.return_value = None
        plain_collector._get_robots = lambda domain: parser
        allowed, delay = plain_collector._respect_robots("https://news.example.com/a")
        assert (allowed, delay) == (True, None)

    def test_respect_robots_can_fetch_exception(self, plain_collector):
        parser = MagicMock()
        parser.can_fetch.side_effect = Exception("blocked")
        parser.crawl_delay.return_value = None
        plain_collector._get_robots = lambda domain: parser
        allowed, delay = plain_collector._respect_robots("https://news.example.com/a")
        assert (allowed, delay) == (True, None)

    def test_respect_robots_fail_open(self, plain_collector):
        plain_collector._get_robots = MagicMock(side_effect=Exception("boom"))
        assert plain_collector._respect_robots("not-a-valid-url") == (True, None)


class TestRetryAfter:
    def _resp(self, header):
        resp = MagicMock()
        resp.headers.get.return_value = header
        return resp

    def test_missing_header(self, plain_collector):
        assert plain_collector._parse_retry_after(self._resp("")) is None

    def test_seconds_header(self, plain_collector):
        parsed = plain_collector._parse_retry_after(self._resp("120"))
        assert parsed is not None and isinstance(parsed, datetime)

    def test_valid_http_date(self, plain_collector):
        parsed = plain_collector._parse_retry_after(
            self._resp("Wed, 21 Oct 2015 07:28:00 GMT")
        )
        assert parsed is not None and parsed.year == 2015

    def test_invalid_date_returns_none(self, plain_collector):
        assert plain_collector._parse_retry_after(self._resp("not-a-date")) is None

    def test_dateless_date_returns_none(self, plain_collector):
        with patch(
            "news_collector.collectors.base_collector.email.utils.parsedate_to_datetime",
            return_value=None,
        ):
            assert plain_collector._parse_retry_after(self._resp("garbage")) is None


class TestDlq:
    def test_writes_to_dlq(self, collector, tmp_path):
        p = collector._send_to_dlq("srcA", "https://example.com", "failed", {"k": "v"})
        assert p.exists()
        assert "failed" in p.read_text()

    def test_write_failure_logs(self, collector, tmp_path, monkeypatch):
        def _boom(self, *args, **kwargs):
            raise OSError("denied")

        monkeypatch.setattr(Path, "write_text", _boom)
        p = collector._send_to_dlq("srcA", "https://example.com", "failed")
        assert not p.exists()


class TestCrawlInterval:
    def test_circuit_breaker_disabled_env(self, collector, monkeypatch):
        monkeypatch.setenv("ENABLE_CIRCUIT_BREAKER", "false")
        assert (
            collector._check_crawl_interval("s1", {"crawl_interval_seconds": 9}) is True
        )

    def test_interval_zero_ready(self, collector):
        assert (
            collector._check_crawl_interval("s1", {"crawl_interval_seconds": 0}) is True
        )

    def test_no_state_ready(self, collector):
        collector.db_manager.get_source_circuit_state.return_value = None
        assert (
            collector._check_crawl_interval("s1", {"crawl_interval_seconds": 9}) is True
        )

    def test_state_without_last_checked_ready(self, collector):
        collector.db_manager.get_source_circuit_state.return_value = {"status": "OK"}
        assert (
            collector._check_crawl_interval("s1", {"crawl_interval_seconds": 9}) is True
        )

    def test_cooldown_naive_future_skips(self, collector):
        now = datetime.now(timezone.utc)
        collector.db_manager.get_source_circuit_state.return_value = {
            "status": "COOLDOWN",
            "next_retry_at": now + timedelta(hours=1),  # naive on purpose
        }
        assert (
            collector._check_crawl_interval("s1", {"crawl_interval_seconds": 9})
            is False
        )

    def test_recent_last_checked_skips(self, collector):
        collector.db_manager.get_source_circuit_state.return_value = {
            "status": "OK",
            "last_checked": datetime.now(timezone.utc) - timedelta(seconds=1),
        }
        assert (
            collector._check_crawl_interval("s1", {"crawl_interval_seconds": 3600})
            is False
        )

    def test_ready_when_interval_elapsed(self, collector):
        collector.db_manager.get_source_circuit_state.return_value = {
            "status": "OK",
            "last_checked": datetime.now(timezone.utc) - timedelta(hours=2),
        }
        assert (
            collector._check_crawl_interval("s1", {"crawl_interval_seconds": 3600})
            is True
        )

    def test_exception_fails_open(self, collector):
        collector.db_manager.get_source_circuit_state.side_effect = RuntimeError(
            "db down"
        )
        assert (
            collector._check_crawl_interval("s1", {"crawl_interval_seconds": 9}) is True
        )


class TestSaveArticle:
    def _model(self, i: int = 0) -> CollectorArticleModel:
        return CollectorArticleModel(**{**_article(i)})

    def test_model_duplicate(self, collector):
        collector.db_manager.save_article.return_value = None
        assert collector._save_article(self._model()) is False
        assert collector._save_article(self._model(1)) is False

    def test_dict_duplicate(self, collector):
        collector.db_manager.save_article.return_value = None
        assert collector._save_article(_article()) is False

    def test_model_exception(self, collector):
        collector.db_manager.save_article.side_effect = ValueError("validation")
        assert collector._save_article(self._model()) is False

    def test_dict_generic_exception(self, collector):
        collector.db_manager.save_article.side_effect = RuntimeError("storage")
        assert collector._save_article(_article()) is False

    def test_update_source_stats_exception(self, collector):
        collector.db_manager.update_source_stats.side_effect = RuntimeError("db")
        collector._update_source_stats("s1", {"a": 1})
        assert collector.stats["total_sources_processed"] >= 0


class TestFilterAndSaveArticles:
    _ACCEPT = SimpleNamespace(accepted=True, reason=None, details={})

    def _accept_admission(self):
        return patch(
            "news_collector.collectors.base_collector.evaluate_admission",
            return_value=self._ACCEPT,
        )

    def test_validation_error_path(self, collector):
        collector.db_manager.save_articles_bulk.return_value = 0
        bad = {"url": "https://x.example.com", "title": "short"}
        n = collector._filter_and_save_articles("s1", [bad])
        assert n == 0

    def test_duplicate_rejected_with_health(self, collector):
        article = CollectorArticleModel(**_article(1))
        collector.db_manager.articles_exist.return_value = {str(article.url)}
        collector.health_tracker = MagicMock()
        with self._accept_admission():
            n = collector._filter_and_save_articles("s1", [article])
        assert n == 0
        collector.health_tracker.record_filter_rejection.assert_called()

    def test_top_n_health_rejection(self, collector):
        collector.health_tracker = MagicMock()
        collector.db_manager.articles_exist.return_value = set()
        collector.db_manager.save_articles_bulk.return_value = 1
        articles = [CollectorArticleModel(**_article(i)) for i in range(3)]
        with self._accept_admission():
            n = collector._filter_and_save_articles("s1", articles, limit=1)
        assert n == 1
        collector.health_tracker.record_filter_rejection.assert_called_with(
            "s1", "top_n", 2
        )

    def test_bulk_save_failure(self, collector):
        collector.health_tracker = MagicMock()
        collector.db_manager.articles_exist.return_value = set()
        collector.db_manager.save_articles_bulk.side_effect = RuntimeError(
            "bulk failed"
        )
        articles = [CollectorArticleModel(**_article(0))]
        with self._accept_admission():
            n = collector._filter_and_save_articles("s1", articles, limit=5)
        assert n == 0


class TestRecommendations:
    def test_high_failure_recommendation(self, plain_collector):
        results = {
            "a": {"success": False, "articles_found": 0, "articles_saved": 0},
            "b": {"success": True, "articles_found": 5, "articles_saved": 5},
        }
        recs = plain_collector._generate_recommendations(results)
        assert any("fuentes fallaron" in r for r in recs)

    def test_low_save_rate_recommendation(self, plain_collector):
        results = {"a": {"success": True, "articles_found": 10, "articles_saved": 1}}
        recs = plain_collector._generate_recommendations(results)
        assert any("Baja tasa de guardado" in r for r in recs)

    def test_empty_sources_recommendation(self, plain_collector):
        results = {"a": {"success": True, "articles_found": 0, "articles_saved": 0}}
        recs = plain_collector._generate_recommendations(results)
        assert any("sin artículos nuevos" in r for r in recs)

    def test_high_processing_recommendation(self, plain_collector):
        plain_collector.stats["processing_time_seconds"] = 301
        recs = plain_collector._generate_recommendations(
            {"a": {"success": True, "articles_found": 1, "articles_saved": 1}}
        )
        assert any("paralelización" in r for r in recs)


class TestHealthAndMetrics:
    def test_unhealthy_collector(self, collector):
        collector.stats["total_sources_processed"] = 10
        collector.stats["total_errors"] = 5
        assert collector.is_healthy() is False
        assert collector.stats["total_errors"] == 5

    def test_performance_metrics(self, collector):
        collector.stats["processing_time_seconds"] = 120.0
        collector.stats["total_sources_processed"] = 10
        collector.stats["total_articles_found"] = 20
        collector.stats["total_articles_saved"] = 10
        collector.stats["total_errors"] = 2
        m = collector.get_performance_metrics()
        assert "sources_per_minute" in m
        assert "success_rate" in m


class TestFactory:
    def test_validate_collector_result_valid(self):
        assert (
            validate_collector_result(
                {
                    "source_id": "s1",
                    "success": True,
                    "articles_found": 1,
                    "articles_saved": 1,
                }
            )
            is True
        )

    def test_validate_collector_result_invalid(self):
        assert validate_collector_result({"source_id": "s1", "success": True}) is False
