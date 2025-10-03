"""Tests for structured logging in collectors."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.collectors.base_collector import BaseCollector
from src.collectors.rss_collector import RSSCollector


class StubModuleLogger:
    """Captures structured log payloads for assertions."""

    def __init__(self) -> None:
        self.records: list[tuple[str, Dict[str, Any]]] = []

    def info(self, payload: Dict[str, Any]) -> None:
        self.records.append(("info", payload))

    def warning(self, payload: Dict[str, Any]) -> None:
        self.records.append(("warning", payload))

    def error(self, payload: Dict[str, Any]) -> None:
        self.records.append(("error", payload))

    def debug(self, payload: Dict[str, Any]) -> None:
        self.records.append(("debug", payload))


class DummyCollector(BaseCollector):
    """Minimal collector that produces deterministic results for logging tests."""

    def collect_from_source(
        self, source_id: str, source_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "source_id": source_id,
            "success": True,
            "articles_found": 1,
            "articles_saved": 1,
            "error_message": None,
            "processing_time": 0.25,
        }


def test_collect_from_multiple_sources_logs_context() -> None:
    """BaseCollector should emit structured logs with trace/session context."""

    collector = DummyCollector()
    stub_logger = StubModuleLogger()
    collector.module_logger = stub_logger

    collector.collect_from_multiple_sources(
        {"source_a": {}}, session_id="session-42", trace_id="trace-99"
    )

    events = {payload["event"]: payload for _level, payload in stub_logger.records}

    assert events["collector.batch.start"]["trace_id"] == "trace-99"
    assert events["collector.batch.completed"]["session_id"] == "session-42"
    assert events["collector.source.completed"]["source_id"] == "source_a"
    assert collector._active_trace_id is None
    assert collector._active_session_id is None


def test_save_article_logs_article_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """_save_article should emit article_id and source context when persisting."""

    saved_article = SimpleNamespace(
        id=123,
        url="https://example.com/article",
        source_id="demo",
    )
    stub_db = SimpleNamespace(save_article=lambda _payload: saved_article)

    monkeypatch.setattr(
        "src.collectors.rss_collector.get_database_manager",
        lambda: stub_db,
    )

    collector = RSSCollector()
    stub_logger = StubModuleLogger()
    collector.module_logger = stub_logger
    collector.db_manager = stub_db

    article_payload = {
        "title": "Structured logging saves the day",
        "source_id": "demo",
        "url": "https://example.com/article",
    }

    assert collector._save_article(article_payload) is True

    saved_events = [
        payload
        for level, payload in stub_logger.records
        if level == "info" and payload.get("event") == "collector.article.saved"
    ]
    assert saved_events, "collector.article.saved event not emitted"
    saved_event = saved_events[-1]

    assert saved_event["article_id"] == 123
    assert saved_event["source_id"] == "demo"
    assert saved_event["details"]["title"].startswith("Structured logging")
