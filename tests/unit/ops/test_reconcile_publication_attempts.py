"""Tests for scripts/ops/reconcile_publication_attempts.py
(Plan 060 / Phase 5b).

The reconciliation logic itself is covered by
``tests/integration/test_publication_reconciliation.py``; this module proves
the CLI wrapper's argument plumbing, summary output and exit code against a
real (temporary) database.
"""

from __future__ import annotations

import sys

import pytest

from news_collector.storage.database import DatabaseManager
from scripts.ops import reconcile_publication_attempts as script


@pytest.fixture()
def db_manager(tmp_path):
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "cli.db"})
    yield manager
    manager.close()


def test_main_dry_run_reports_summary(
    db_manager: DatabaseManager,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    monkeypatch.setattr(script, "DatabaseManager", lambda: db_manager)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reconcile_publication_attempts.py",
            "--stale-minutes",
            "30",
            "--limit",
            "5",
            "--receipt-limit",
            "7",
            "--dry-run",
        ],
    )

    exit_code = script.main()

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "[reconcile-publications] scanned=0" in out
    assert "[reconcile-publications] dry-run: no rows were written" in out


def test_main_real_run_exits_zero(
    db_manager: DatabaseManager,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    monkeypatch.setattr(script, "DatabaseManager", lambda: db_manager)
    monkeypatch.setattr(sys, "argv", ["reconcile_publication_attempts.py"])

    exit_code = script.main()

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "[reconcile-publications] scanned=0" in out
    assert "dry-run" not in out
