"""Observability focused tests for structured logging and metrics."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import main


class StructuredModuleLogger:
    """Proxy logger that forwards messages to the stdlib logging module."""

    def __init__(self, module_name: str) -> None:
        self._logger = logging.getLogger(f"test.{module_name}")

    def info(self, message: Any) -> None:  # pragma: no cover - trivial proxy
        self._logger.info(message)

    def warning(self, message: Any) -> None:  # pragma: no cover - trivial proxy
        self._logger.warning(message)

    def error(self, message: Any) -> None:  # pragma: no cover - trivial proxy
        self._logger.error(message)


class StubLoggerFactory:
    """Minimal logger factory compatible with the NewsCollectorSystem."""

    def __init__(self) -> None:
        self.modules: Dict[str, StructuredModuleLogger] = {}

    def create_module_logger(self, module_name: str) -> StructuredModuleLogger:
        if module_name not in self.modules:
            self.modules[module_name] = StructuredModuleLogger(module_name)
        return self.modules[module_name]

    def log_performance_metrics(
        self, metrics: Dict[str, Any], context: str = ""
    ) -> None:
        logging.getLogger("test.performance").info(
            {"metrics": metrics, "context": context}
        )

    def log_error_with_context(
        self, error: Exception, context: Dict[str, Any] | None = None
    ) -> None:
        logging.getLogger("test.errors").error(
            {"error": str(error), "context": context}
        )

    def log_system_startup(self, **_kwargs: Any) -> None:  # pragma: no cover - stub
        return None

    def log_system_health(self) -> None:  # pragma: no cover - stub
        return None


class StubMetrics:
    """Captures metric events for assertions."""

    def __init__(self) -> None:
        self.ingest_events = []
        self.error_events = []

    def record_ingest(self, **payload: Any) -> None:
        self.ingest_events.append(payload)

    def record_error(self, **payload: Any) -> None:
        self.error_events.append(payload)


def test_collection_cycle_logs_and_emits_metrics(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """run_collection_cycle should emit structured logs and metrics per source."""

    caplog.set_level(logging.INFO)

    logger_factory = StubLoggerFactory()
    metrics_stub = StubMetrics()

    system = main.NewsCollectorSystem()
    system.logger = logger_factory
    system.system_logger = logger_factory.create_module_logger("system")
    system.metrics = metrics_stub
    system.is_initialized = True

    collection_results = {
        "collection_summary": {
            "sources_processed": 2,
            "articles_found": 4,
            "articles_saved": 2,
            "success_rate_percent": 50,
        },
        "source_details": {
            "source_a": {
                "success": True,
                "articles_found": 3,
                "articles_saved": 2,
                "processing_time": 1.25,
            },
            "source_b": {
                "success": False,
                "articles_found": 1,
                "articles_saved": 0,
                "processing_time": 0.5,
                "error_message": "timeout",
            },
        },
    }

    scoring_results = {"statistics": {"articles_scored": 2}}
    final_selection = {"success": True, "selected_count": 1, "articles": []}
    final_summary = {
        "summary": {
            "sources_processed": 2,
            "articles_found": 4,
            "articles_saved": 2,
            "articles_scored": 2,
            "final_selection_count": 1,
        },
        "performance_metrics": {
            "total_duration_seconds": 1.0,
            "articles_per_second": 4.0,
            "sources_per_minute": 2.0,
            "success_rate_percent": 50,
        },
        "session_info": {
            "session_id": "sample-session",
            "system_id": system.system_id,
            "start_time": system.start_time.isoformat(),
            "end_time": system.start_time.isoformat(),
            "duration_seconds": 1.0,
        },
    }

    monkeypatch.setattr(
        main.NewsCollectorSystem,
        "_get_sources_to_process",
        lambda self, _sources_filter: {"source_a": {}, "source_b": {}},
    )
    monkeypatch.setattr(
        main.NewsCollectorSystem,
        "_execute_collection",
        lambda self, _sources, _dry_run: collection_results,
    )
    monkeypatch.setattr(
        main.NewsCollectorSystem,
        "_execute_scoring",
        lambda self, _collection_results, _dry_run: scoring_results,
    )
    monkeypatch.setattr(
        main.NewsCollectorSystem,
        "_execute_final_selection",
        lambda self, _scoring_results: final_selection,
    )
    monkeypatch.setattr(
        main.NewsCollectorSystem,
        "_generate_session_report",
        lambda self, *_args, **_kwargs: final_summary,
    )

    result = system.run_collection_cycle(trace_id="test-trace")

    assert result["summary"]["articles_saved"] == 2
    assert len(metrics_stub.ingest_events) == 1
    assert metrics_stub.ingest_events[0]["source_id"] == "source_a"
    assert metrics_stub.ingest_events[0]["trace_id"] == "test-trace"

    assert len(metrics_stub.error_events) == 1
    assert metrics_stub.error_events[0]["source_id"] == "source_b"

    structured_messages = [
        record.msg for record in caplog.records if isinstance(record.msg, dict)
    ]
    assert any(
        msg.get("event") == "collector.source.completed"
        and msg.get("source_id") == "source_a"
        for msg in structured_messages
    )
    assert any(
        msg.get("event") == "collector.source.failed"
        and msg.get("source_id") == "source_b"
        for msg in structured_messages
    )


def test_cli_logging(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """run_simple_collection should log lifecycle events via the module logger."""

    from run_collector import run_simple_collection

    caplog.set_level(logging.INFO)

    logger_factory = StubLoggerFactory()
    monkeypatch.setattr("run_collector.setup_logging", lambda: logger_factory)

    class DummySystem:
        def initialize(self) -> bool:
            return True

        def run_collection_cycle(self, **_kwargs: Any) -> Dict[str, Any]:
            return {
                "session_info": {"session_id": "cli-session"},
                "summary": {"sources_processed": 1},
            }

    monkeypatch.setattr("run_collector.create_system", lambda: DummySystem())

    args = SimpleNamespace(
        quiet=True,
        sources=None,
        dry_run=False,
        show_articles=0,
        verbose=False,
    )

    assert run_simple_collection(args) is True

    structured_messages = [
        record.msg for record in caplog.records if isinstance(record.msg, dict)
    ]
    assert any(
        msg.get("event") == "cli.collection.completed" for msg in structured_messages
    )
