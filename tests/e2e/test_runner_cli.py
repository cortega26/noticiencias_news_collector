"""End-to-end style tests for the ``run_collector`` CLI entry point."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

import run_collector


def _build_results_summary() -> Dict[str, Any]:
    """Return a minimal successful result payload for the fake system."""

    return {
        "summary": {
            "sources_processed": 1,
            "articles_found": 3,
            "articles_saved": 2,
            "articles_scored": 2,
            "final_selection_count": 1,
        },
        "performance_metrics": {
            "total_duration_seconds": 1.0,
            "success_rate_percent": 100.0,
            "articles_per_second": 3.0,
        },
    }


@dataclass
class StructuredLogger:
    """Collect structured log payloads for assertions."""

    events: List[Dict[str, Any]] = field(default_factory=list)

    def info(self, payload: Dict[str, Any]) -> None:
        self.events.append({"level": "info", "payload": payload})

    def error(self, payload: Dict[str, Any]) -> None:
        self.events.append({"level": "error", "payload": payload})


@dataclass
class LoggerFactory:
    """Return :class:`StructuredLogger` instances that share the same store."""

    events: List[Dict[str, Any]] = field(default_factory=list)

    def create_module_logger(self, _: str) -> StructuredLogger:
        return StructuredLogger(self.events)


@dataclass
class FakeSystem:
    """Minimal implementation of the collector system used by the CLI."""

    initialize_result: bool = True
    raise_on_run: bool = False
    run_result: Dict[str, Any] = field(default_factory=_build_results_summary)
    run_kwargs: Dict[str, Any] = field(default_factory=dict)

    def initialize(self) -> bool:
        return self.initialize_result

    def run_collection_cycle(
        self,
        *,
        sources_filter: Optional[List[str]],
        dry_run: bool,
        trace_id: str,
    ) -> Dict[str, Any]:
        if self.raise_on_run:
            raise RuntimeError("collection failed")
        self.run_kwargs = {
            "sources_filter": sources_filter,
            "dry_run": dry_run,
            "trace_id": trace_id,
        }
        return self.run_result

    @staticmethod
    def get_top_articles(_: int) -> List[Dict[str, Any]]:
        return []


@pytest.fixture(autouse=True)
def stub_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide a lightweight catalog for CLI flows."""

    monkeypatch.setattr(
        run_collector,
        "ALL_SOURCES",
        {
            "alpha": {
                "category": "science",
                "name": "Alpha Source",
                "credibility_score": 0.8,
            },
            "beta": {
                "category": "technology",
                "name": "Beta Source",
                "credibility_score": 0.7,
            },
        },
    )


@pytest.fixture
def logger_factory(monkeypatch: pytest.MonkeyPatch) -> LoggerFactory:
    """Patch ``setup_logging`` so tests can inspect structured payloads."""

    factory = LoggerFactory()
    monkeypatch.setattr(run_collector, "setup_logging", lambda: factory)
    return factory


@pytest.fixture
def stub_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure dependency checks always pass during CLI invocations."""

    monkeypatch.setattr(run_collector, "check_dependencies", lambda: True)


def _invoke_cli(monkeypatch: pytest.MonkeyPatch, argv: List[str]) -> SystemExit:
    """Execute ``run_collector.main`` with the provided arguments."""

    monkeypatch.setattr(sys, "argv", ["run_collector.py", *argv])
    with pytest.raises(SystemExit) as exc_info:
        run_collector.main()
    return exc_info.value


def test_cli_dry_run_invokes_collection(monkeypatch: pytest.MonkeyPatch, logger_factory: LoggerFactory, stub_dependencies: None, capsys: pytest.CaptureFixture[str]) -> None:
    """``--dry-run`` should forward the flag and report simulation mode."""

    system = FakeSystem()
    monkeypatch.setattr(run_collector, "create_system", lambda: system)

    exit_code = _invoke_cli(monkeypatch, ["--dry-run", "--show-articles", "0"]).code

    captured = capsys.readouterr().out
    assert "🧪 MODO SIMULACIÓN" in captured
    assert exit_code == 0
    assert system.run_kwargs["dry_run"] is True
    assert system.run_kwargs["sources_filter"] is None
    assert isinstance(system.run_kwargs["trace_id"], str)
    assert any(event["payload"]["event"] == "cli.collection.completed" for event in logger_factory.events)


def test_cli_filters_sources(monkeypatch: pytest.MonkeyPatch, logger_factory: LoggerFactory, stub_dependencies: None, capsys: pytest.CaptureFixture[str]) -> None:
    """Invalid sources should be reported while valid ones are processed."""

    system = FakeSystem()
    monkeypatch.setattr(run_collector, "create_system", lambda: system)

    exit_code = _invoke_cli(
        monkeypatch,
        ["--sources", "alpha", "missing", "--show-articles", "0"],
    ).code

    captured = capsys.readouterr().out
    assert exit_code == 0
    assert "⚠️  Fuentes no encontradas: missing" in captured
    assert system.run_kwargs["sources_filter"] == ["alpha"]
    assert any(
        event["payload"].get("event") == "cli.sources.invalid"
        for event in logger_factory.events
    )


def test_cli_list_sources(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``--list-sources`` should print the catalog and exit early."""

    exit_code = _invoke_cli(monkeypatch, ["--list-sources"]).code
    captured = capsys.readouterr().out
    assert exit_code == 0
    assert "📚 FUENTES DISPONIBLES" in captured


def test_cli_check_deps(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``--check-deps`` should invoke the helper and exit successfully."""

    monkeypatch.setattr(run_collector, "check_dependencies", lambda: True)
    exit_code = _invoke_cli(monkeypatch, ["--check-deps"]).code
    captured = capsys.readouterr().out
    assert exit_code == 0
    assert "✅ Todas las dependencias están instaladas" in captured


def test_cli_healthcheck_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Healthcheck success should exit zero and forward thresholds."""

    captured_kwargs: Dict[str, Any] = {}

    def stub_run_cli(**kwargs: Any) -> bool:
        captured_kwargs.update(kwargs)
        return True

    module = SimpleNamespace(run_cli=stub_run_cli)
    monkeypatch.setitem(sys.modules, "scripts.healthcheck", module)

    exit_code = _invoke_cli(
        monkeypatch,
        [
            "--healthcheck",
            "--healthcheck-max-pending",
            "25",
            "--healthcheck-max-ingest-minutes",
            "10",
        ],
    ).code

    assert exit_code == 0
    assert captured_kwargs == {"max_pending": 25, "max_ingest_lag_minutes": 10}


def test_cli_healthcheck_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Healthcheck failure should produce a non-zero exit code."""

    module = SimpleNamespace(run_cli=lambda **_: False)
    monkeypatch.setitem(sys.modules, "scripts.healthcheck", module)

    exit_code = _invoke_cli(
        monkeypatch,
        [
            "--healthcheck",
            "--healthcheck-max-pending",
            "99",
        ],
    ).code

    assert exit_code == 1


def test_cli_initialize_failure_logs_error(
    monkeypatch: pytest.MonkeyPatch,
    logger_factory: LoggerFactory,
    stub_dependencies: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Failed system initialization should emit a structured error log."""

    system = FakeSystem(initialize_result=False)
    monkeypatch.setattr(run_collector, "create_system", lambda: system)

    exit_code = _invoke_cli(monkeypatch, ["--show-articles", "0"]).code

    captured = capsys.readouterr().out
    assert exit_code == 1
    assert "❌ Error durante inicialización del sistema" in captured
    assert any(
        event["payload"].get("event") == "cli.initialize.failed"
        for event in logger_factory.events
    )


def test_cli_collection_exception_logs_error(
    monkeypatch: pytest.MonkeyPatch,
    logger_factory: LoggerFactory,
    stub_dependencies: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unexpected exceptions should be surfaced via structured logging."""

    system = FakeSystem(raise_on_run=True)
    monkeypatch.setattr(run_collector, "create_system", lambda: system)

    exit_code = _invoke_cli(monkeypatch, ["--show-articles", "0"]).code

    captured = capsys.readouterr().out
    assert exit_code == 1
    assert "❌ Error durante ejecución: collection failed" in captured
    assert any(
        event["payload"].get("event") == "cli.collection.error"
        for event in logger_factory.events
    )

