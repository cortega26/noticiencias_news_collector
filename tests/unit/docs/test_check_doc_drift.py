"""Tests for scripts/check_doc_drift.py (plan 043, backend doc-drift gate).

The script resolves docs relative to DOC_DRIFT_ROOT / DOC_DRIFT_FILES, so
these tests run it against fixture doc trees plus a fixture Makefile, and a
fixture sibling root for cross-repo checks.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "check_doc_drift.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "doc-drift"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import check_doc_drift  # noqa: E402


def run_check(
    root: str,
    docs: list[str],
    *,
    sibling_root: str | None = None,
    makefile: str | None = None,
) -> tuple[str, int]:
    env = dict(os.environ)
    env["DOC_DRIFT_ROOT"] = root
    env["DOC_DRIFT_FILES"] = ",".join(docs)
    if sibling_root is not None:
        env["DOC_DRIFT_SIBLING_ROOT"] = sibling_root
    cmd = [sys.executable, str(SCRIPT)]
    if makefile is not None:
        cmd += ["--makefile", makefile]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return proc.stdout + proc.stderr, proc.returncode


def test_passes_on_valid_fixture():
    combined, exit_code = run_check(
        str(FIXTURES / "valid"),
        ["README.md"],
    )
    assert exit_code == 0, combined
    assert "[check:doc-drift] OK" in combined


def test_flags_broken_path():
    combined, exit_code = run_check(
        str(FIXTURES / "broken"),
        ["README.md"],
    )
    assert exit_code == 1, combined
    assert "broken path" in combined
    assert "MISSING.py" in combined


def test_flags_unknown_make_target():
    combined, exit_code = run_check(
        str(FIXTURES / "make-target"),
        ["README.md"],
        makefile=str(FIXTURES / "make-target" / "Makefile"),
    )
    assert exit_code == 1, combined
    assert "unknown make target" in combined
    assert "make nonexistent-target" in combined


def test_accepts_known_make_target():
    combined, exit_code = run_check(
        str(FIXTURES / "make-target"),
        ["AGENTS.md"],
        makefile=str(FIXTURES / "make-target" / "Makefile"),
    )
    assert exit_code == 0, combined
    assert "[check:doc-drift] OK" in combined


def test_flags_stale_schema_path():
    combined, exit_code = run_check(
        str(FIXTURES / "stale"),
        ["README.md"],
    )
    assert exit_code == 1, combined
    assert "stale declared claim" in combined
    assert "src/content/config.ts" in combined
    assert "src/content.config.ts" in combined


def test_flags_stale_publication_date_fallback():
    combined, exit_code = run_check(
        str(FIXTURES / "stale"),
        ["README.md"],
    )
    assert exit_code == 1, combined
    assert "stale declared claim" in combined
    assert "current date as last resort" in combined


def test_flags_stale_site_host_with_sibling():
    combined, exit_code = run_check(
        str(FIXTURES / "stale"),
        ["README.md"],
        sibling_root=str(FIXTURES / "sibling-ok" / "_sibling"),
    )
    assert exit_code == 1, combined
    assert "stale declared claim" in combined
    assert "noticiencias.cl" in combined
    assert "https://noticiencias.com" in combined


def test_flags_stale_python_major():
    combined, exit_code = run_check(
        str(FIXTURES / "stale-python"),
        ["README.md"],
    )
    assert exit_code == 1, combined
    assert "stale declared claim" in combined
    assert "Python 3.9" in combined
    assert "Python 3.13" in combined


def test_cross_repo_ref_resolves_with_sibling():
    combined, exit_code = run_check(
        str(FIXTURES / "sibling-ok"),
        ["README.md"],
        sibling_root=str(FIXTURES / "sibling-ok" / "_sibling"),
    )
    assert exit_code == 0, combined
    assert "[check:doc-drift] OK" in combined


def test_cross_repo_ref_flags_missing_sibling_file():
    combined, exit_code = run_check(
        str(FIXTURES / "sibling-broken"),
        ["README.md"],
        sibling_root=str(FIXTURES / "sibling-broken" / "_sibling"),
    )
    assert exit_code == 1, combined
    assert "broken path" in combined
    assert "MISSING.md" in combined


def test_cross_repo_ref_skipped_without_sibling():
    combined, exit_code = run_check(
        str(FIXTURES / "sibling-broken"),
        ["README.md"],
        sibling_root=str(FIXTURES / "no-such-sibling"),
    )
    assert exit_code == 0, combined
    assert "[check:doc-drift] OK" in combined


def test_live_repo_docs_pass():
    # Force the sibling to be absent so the live check is deterministic in
    # any environment (CI workspace layout differs from local: the sibling
    # path may or may not exist; the check must pass on the backend alone).
    combined, exit_code = run_check(
        str(REPO_ROOT),
        [],
        sibling_root=str(REPO_ROOT / "no-such-sibling"),
    )
    assert exit_code == 0, combined
    assert "[check:doc-drift] OK" in combined


def test_lookups_mirror_frontend_semantics():
    """The backend resolver treats the same shapes as the frontend: bare
    filenames resolve against search dirs, member expressions and commands
    are skipped, and dotfiles are not chased."""
    assert check_doc_drift.looks_like_file_path("news_collector/contracts/adapters.py")
    assert check_doc_drift.looks_like_file_path("Makefile")
    assert not check_doc_drift.looks_like_file_path("data.permalink")
    assert not check_doc_drift.looks_like_file_path("pip-audit -r requirements.lock")
    assert not check_doc_drift.looks_like_file_path("~/.cloudflared/config.yml")
    assert not check_doc_drift.looks_like_file_path("apps/refinery/.env")
    assert check_doc_drift.looks_like_file_path("serving/api.py")
    assert (
        check_doc_drift.strip_line_numbers("tests/test_x.py::test_case")
        == "tests/test_x.py"
    )
    assert check_doc_drift.strip_line_numbers("foo.py:122") == "foo.py"
