"""Fail-open fallbacks must still say so (silent-failure audit, 2026-10).

Each case forces the failure that used to be swallowed (``return None``, ``{}``,
defaults) and checks it now leaves a WARNING, once per process where the
failure would otherwise repeat on every call.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from news_collector.collectors.base_collector import BaseCollector
from news_collector.utils import warn_once as wo


class _Rec:
    """Stand-in logger recording ``(level, formatted message)``."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def __getattr__(self, level: str):
        if level not in {"debug", "info", "warning", "error", "critical"}:
            raise AttributeError(level)

        def log(msg: Any, *args: Any, **_kw: Any) -> None:
            self.records.append((level, str(msg).format(*args) if args else str(msg)))

        return log

    def warnings(self, containing: str = "") -> list[str]:
        return [m for lvl, m in self.records if lvl == "warning" and containing in m]


@pytest.fixture(autouse=True)
def _fresh_warn_once():
    wo.reset()
    yield
    wo.reset()


def _boom(*_a: Any, **_kw: Any):
    raise RuntimeError("boom")


# -------------------------------------------------------------------- helper


def test_warn_once_logs_first_time_only_per_key():
    rec = _Rec()
    assert wo.warn_once(rec, "k", "hello {}", "x") is True
    assert wo.warn_once(rec, "k", "hello {}", "y") is False
    assert wo.warn_once(rec, "other", "hello") is True
    assert rec.warnings() == ["hello x", "hello"]


# ------------------------------------------------------------------ the gaps


def test_editor_config_failure_warns_and_uses_defaults(monkeypatch, tmp_path: Path):
    from noticiencias import config_manager

    from news_collector.components.editorial import ai_editor

    rec = _Rec()
    monkeypatch.setattr(ai_editor, "logger", rec)
    monkeypatch.setattr(ai_editor, "load_config", _boom)
    monkeypatch.setattr(config_manager, "_project_root", lambda: tmp_path)
    editor = ai_editor.EditorAgent(api_url="http://localhost", model="m")
    assert editor.min_content_length == 750 and editor.max_headline_retries == 2
    (msg,) = rec.warnings("config unavailable")
    assert "RuntimeError: boom" in msg and "built-in defaults" in msg


def test_production_metrics_read_failure_warns_once(monkeypatch):
    from news_collector.observability import enrichment_metrics_store as ems

    rec = _Rec()
    monkeypatch.setattr(ems, "logger", rec)
    store = object.__new__(ems.ProductionReadonlyStore)
    store._lock = threading.Lock()
    store.conn = MagicMock()
    store.conn.cursor.side_effect = sqlite3.OperationalError("database is locked")
    store._connect = lambda: True
    store._reset_connection = MagicMock()
    assert store.get_all_metrics() == {}
    assert store.get_all_metrics() == {}
    (msg,) = rec.warnings("enrichment metrics")
    assert "database is locked" in msg
    assert store._reset_connection.call_count == 2  # behaviour unchanged


def test_activity_monitor_read_failure_warns_once(monkeypatch, tmp_path: Path):
    from news_collector.system import activity_monitor as am

    rec = _Rec()
    monkeypatch.setattr(am, "logger", rec)
    log = tmp_path / "collector.log"
    log.write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(am.EventAggregator, "aggregate", staticmethod(_boom))
    monitor = am.ActivityMonitor(log_path=log)
    assert monitor.get_recent_activity() == []
    assert monitor.get_recent_activity() == []
    (msg,) = rec.warnings("recent activity")
    assert "boom" in msg


def test_spacy_blank_model_failure_warns_once_per_language(monkeypatch):
    from news_collector.enrichment import nlp_stack

    rec = _Rec()
    monkeypatch.setattr(nlp_stack, "logger", rec)
    monkeypatch.setattr(nlp_stack, "spacy", SimpleNamespace(blank=_boom))
    stack = object.__new__(nlp_stack.ConfigurableNLPStack)
    stack._nlp_models = {}
    stack._resolve_entity_patterns = lambda _language: None
    assert stack._get_spacy_model("xx") is None
    assert stack._get_spacy_model("xx") is None
    assert stack._get_spacy_model("yy") is None
    assert len(rec.warnings("blank model")) == 2


def test_crossref_failure_warns_once_per_error_kind():
    from news_collector.enrichment import scholarly

    rec = _Rec()
    scholarly.logger, original = rec, scholarly.logger
    try:
        enricher = scholarly.ScholarlyMetadataEnricher()
        enricher.session = MagicMock()
        enricher.session.get.side_effect = requests.ConnectionError("down")
        assert enricher.fetch_metadata("10.1/a") is None
        assert enricher.fetch_metadata("10.1/b") is None
    finally:
        scholarly.logger = original
    (msg,) = rec.warnings("Crossref")
    assert "10.1/a" in msg and "down" in msg


def test_r2_unreadable_env_warns_once_and_is_unset(monkeypatch):
    from noticiencias import config_manager

    from news_collector.infrastructure import r2_client

    rec = _Rec()
    monkeypatch.setattr(r2_client, "logger", rec)
    monkeypatch.delenv("LOUD_R2_KEY", raising=False)
    monkeypatch.setattr(config_manager, "load_env_overrides", _boom)
    assert r2_client._read_env("LOUD_R2_KEY") is None
    assert r2_client._read_env("LOUD_R2_KEY") is None
    (msg,) = rec.warnings("LOUD_R2_KEY")
    assert "treating it as unset" in msg


class _Concrete(BaseCollector):
    def collect_from_source(self, source_id, source_config):
        return {"success": True}

    def _create_session(self):
        pass


def _robots_cfg(monkeypatch):
    from news_collector.collectors import base_collector

    cfg = SimpleNamespace(
        robots_config={"respect_robots": True, "cache_ttl_seconds": 0},
        collection_config={"user_agent": "test-agent"},
    )
    monkeypatch.setattr(base_collector, "get_runtime_config", lambda: cfg)


def _collector(cls):
    collector = object.__new__(cls)
    collector.module_logger = _Rec()
    collector._robots_cache = {}
    return collector


def test_robots_unreachable_warns_fail_open_once_per_domain(monkeypatch):
    from news_collector.collectors import base_collector

    _robots_cfg(monkeypatch)
    collector = _collector(_Concrete)
    monkeypatch.setattr(base_collector.httpx, "get", _boom)
    monkeypatch.setattr(
        "news_collector.utils.security.validate_url_safety", lambda _url: None
    )
    assert collector._get_robots("example.org") is None
    assert collector._get_robots("example.org") is None
    assert collector._get_robots("other.org") is None
    warnings = collector.module_logger.warnings("fail-open")
    assert len(warnings) == 2 and "example.org" in warnings[0]


def test_robots_5xx_warns_but_4xx_is_silent(monkeypatch):
    from news_collector.collectors import base_collector

    _robots_cfg(monkeypatch)
    collector = _collector(_Concrete)
    monkeypatch.setattr(
        "news_collector.utils.security.validate_url_safety", lambda _url: None
    )
    for status, domain in ((404, "a.org"), (503, "b.org")):
        monkeypatch.setattr(
            base_collector.httpx,
            "get",
            lambda *_a, _s=status, **_k: SimpleNamespace(status_code=_s, text=""),
        )
        assert collector._get_robots(domain) is None
    (msg,) = collector.module_logger.warnings("fail-open")
    assert "b.org" in msg and "503" in msg


def test_robots_rule_evaluation_failure_warns_and_allows(monkeypatch):
    from news_collector.collectors import base_collector

    _robots_cfg(monkeypatch)
    collector = _collector(_Concrete)
    rules = SimpleNamespace(can_fetch=_boom, crawl_delay=lambda _ua: None)
    collector._get_robots = lambda _domain: rules
    allowed, delay = collector._respect_robots("https://example.org/page")
    assert allowed is True and delay is None
    (msg,) = collector.module_logger.warnings("could not be evaluated")
    assert "example.org" in msg


@pytest.mark.asyncio
async def test_article_body_failure_is_logged_with_its_url():
    from news_collector.collectors.html_collector import HtmlCollector

    collector = _collector(HtmlCollector)
    client = MagicMock()
    client.get = MagicMock(side_effect=RuntimeError("tls reset"))
    assert (
        await collector._fetch_article_content(client, "https://example.org/a", {})
        is None
    )
    (msg,) = collector.module_logger.warnings("Article body fetch failed")
    assert "https://example.org/a" in msg and "tls reset" in msg


@pytest.mark.asyncio
async def test_html_network_failure_after_retries_is_logged(monkeypatch):
    from unittest.mock import AsyncMock, patch

    import httpx

    from news_collector.collectors.html_collector import HtmlCollector

    with patch("news_collector.collectors.html_collector.get_runtime_config"):
        collector = HtmlCollector(logger_factory=MagicMock())
    collector.db_manager = MagicMock()
    collector.db_manager.get_source_feed_metadata.return_value = None
    collector._emit_log = MagicMock()
    collector._backoff_sleep_async = AsyncMock()
    client = MagicMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False
    client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    with patch("httpx.AsyncClient", return_value=client):
        result = await collector._fetch_html_conditional(
            "https://example.org/news", "s1", {"url": "https://example.org/news"}
        )
    assert result == (None, None)
    (call,) = [
        c
        for c in collector._emit_log.call_args_list
        if c.args[:2] == ("warning", "collector.fetch.network_failure")
    ]
    assert call.kwargs["source_id"] == "s1" and call.kwargs["details"] == {
        "attempts": 3
    }
