"""Tests for scripts/check_doc_review.py (plan 043 step 4, changed-file gate).

The gate fails when a protected path (contracts/, config schema, workflows,
serving/, storage/) changes without an active-doc change in the same set,
and passes for archive/audit-only edits.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "check_doc_review.py"


def run_gate(files: list[str]) -> tuple[str, int]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--changed", *files],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.stdout + proc.stderr, proc.returncode


def test_contract_change_without_doc_review_fails():
    combined, exit_code = run_gate(
        ["news_collector/contracts/frontend_schema.py", "tests/unit/test_x.py"]
    )
    assert exit_code == 1, combined
    assert "FAIL" in combined
    assert "frontend_schema.py" in combined


def test_contract_change_with_doc_review_passes():
    combined, exit_code = run_gate(
        [
            "news_collector/contracts/frontend_schema.py",
            "docs/PIPELINE_CONTRACTS.md",
        ]
    )
    assert exit_code == 0, combined
    assert "OK" in combined


def test_config_schema_change_fails():
    combined, exit_code = run_gate(["noticiencias/config_schema.py"])
    assert exit_code == 1, combined


def test_workflow_change_fails():
    combined, exit_code = run_gate([".github/workflows/ci.yml"])
    assert exit_code == 1, combined


def test_serving_and_storage_changes_fail():
    combined, exit_code = run_gate(
        ["news_collector/serving/api.py", "news_collector/storage/database.py"]
    )
    assert exit_code == 1, combined


def test_archive_only_edits_pass():
    combined, exit_code = run_gate(
        ["docs/audits/2026-08-old-audit.md", "docs/archive/x.md"]
    )
    assert exit_code == 0, combined
    assert "exempt" in combined


def test_plans_only_edits_pass():
    combined, exit_code = run_gate(["plans/README.md", "plans/043/spec.md"])
    assert exit_code == 0, combined


def test_unrelated_code_changes_pass():
    combined, exit_code = run_gate(
        ["tests/unit/test_x.py", "news_collector/scoring/coordinator.py"]
    )
    assert exit_code == 0, combined


def test_no_changes_pass():
    combined, exit_code = run_gate([])
    assert exit_code == 0, combined
