"""End-to-end style tests for the run_collector CLI entry point."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Sequence
from unittest.mock import Mock

import pytest

import run_collector


@pytest.fixture(autouse=True)
def _reset_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure LOG_LEVEL is unset between tests."""
    monkeypatch.delenv("LOG_LEVEL", raising=False)


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Prepare a predictable environment for CLI tests."""

    collection_result = {
        "summary": {
            "sources_processed": 2,
            "articles_found": 4,
            "articles_saved": 3,
            "articles_scored": 3,
            "final_selection_count": 2,
        },
        "performance_metrics": {
            "total_duration_seconds": 1.0,
            "success_rate_percent": 100.0,
            "articles_per_second": 4.0,
        },
        "session_info": {"session_id": "session-123"},
    }

    stub_system = SimpleNamespace(
        initialize=Mock(return_value=True),
        run_collection_cycle=Mock(return_value=collection_result),
        get_top_articles=Mock(return_value=[]),
    )

    logger = Mock()
    logger.info = Mock()

    logger_factory = Mock()
    logger_factory.create_module_logger.return_value = logger

    check_dependencies = Mock(return_value=True)

    monkeypatch.setattr(
        run_collector,
        "ALL_SOURCES",
        {
            "valid_source": {
                "category": "astronomy",
                "name": "Valid Source",
                "credibility_score": 0.8,
            },
            "secondary_source": {
                "category": "astronomy",
                "name": "Secondary Source",
                "credibility_score": 0.6,
            },
        },
    )
    monkeypatch.setattr(run_collector, "create_system", Mock(return_value=stub_system))
    monkeypatch.setattr(
        run_collector, "setup_logging", Mock(return_value=logger_factory)
    )
    monkeypatch.setattr(run_collector, "check_dependencies", check_dependencies)

    return SimpleNamespace(
        stub_system=stub_system,
        logger=logger,
        logger_factory=logger_factory,
        check_dependencies=check_dependencies,
    )


def _invoke_cli(monkeypatch: pytest.MonkeyPatch, args: Sequence[str]) -> int:
    """Execute the CLI entry point and capture its exit code."""

    monkeypatch.setattr(sys, "argv", ["run_collector.py", *args])
    with pytest.raises(SystemExit) as exc_info:
        run_collector.main()
    return int(exc_info.value.code)


def test_cli_dry_run_success(
    cli_env: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI should complete in dry-run mode and surface simulation messaging."""

    exit_code = _invoke_cli(monkeypatch, ["--dry-run", "--show-articles", "0"])

    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "🧪 MODO SIMULACIÓN" in captured
    assert "🌐 Procesando todas" in captured

    cli_env.stub_system.run_collection_cycle.assert_called_once()
    call_kwargs = cli_env.stub_system.run_collection_cycle.call_args.kwargs
    assert call_kwargs["dry_run"] is True
    assert call_kwargs["sources_filter"] is None


def test_cli_sources_filter_and_validation(
    cli_env: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI should filter requested sources and warn about invalid entries."""

    exit_code = _invoke_cli(
        monkeypatch,
        ["--sources", "valid_source", "missing_source", "--show-articles", "0"],
    )

    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "⚠️  Fuentes no encontradas: missing_source" in captured
    assert "Procesando 1 fuentes específicas: valid_source" in captured

    cli_env.stub_system.run_collection_cycle.assert_called_once()
    call_kwargs = cli_env.stub_system.run_collection_cycle.call_args.kwargs
    assert call_kwargs["sources_filter"] == ["valid_source", "missing_source"]
    assert call_kwargs["dry_run"] is False


def test_cli_list_sources(
    cli_env: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Listing sources should print catalog information and exit cleanly."""

    exit_code = _invoke_cli(monkeypatch, ["--list-sources"])

    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "📚 FUENTES DISPONIBLES" in captured
    assert "Valid Source" in captured

    # No system interactions should occur during listing
    cli_env.stub_system.initialize.assert_not_called()
    cli_env.stub_system.run_collection_cycle.assert_not_called()


def test_cli_check_dependencies(
    cli_env: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dependency checks should invoke the helper and exit successfully."""

    exit_code = _invoke_cli(monkeypatch, ["--check-deps"])

    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "✅ Todas las dependencias están instaladas" in captured
    cli_env.check_dependencies.assert_called_once()


@pytest.mark.parametrize(
    "healthcheck_result, expected_exit",
    [
        (True, 0),
        (False, 1),
    ],
)
def test_cli_healthcheck_exit_codes(
    cli_env: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    healthcheck_result: bool,
    expected_exit: int,
) -> None:
    """The healthcheck flag should propagate results and exit accordingly."""

    received_kwargs = {}

    def _stub_run_cli(
        *, max_pending: int | None, max_ingest_lag_minutes: int | None
    ) -> bool:
        received_kwargs["max_pending"] = max_pending
        received_kwargs["max_ingest_lag_minutes"] = max_ingest_lag_minutes
        return healthcheck_result

    monkeypatch.setattr("scripts.healthcheck.run_cli", _stub_run_cli)

    exit_code = _invoke_cli(
        monkeypatch,
        [
            "--healthcheck",
            "--healthcheck-max-pending",
            "25",
            "--healthcheck-max-ingest-minutes",
            "10",
        ],
    )

    assert exit_code == expected_exit
    assert received_kwargs == {"max_pending": 25, "max_ingest_lag_minutes": 10}
