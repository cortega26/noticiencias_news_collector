"""Tests for scripts/check_lock_parity.py (plan 144).

The gate compares `requirements.lock` with the running environment. These
tests use fixture locks (and a faked installed-version lookup) so the unit
suite never depends on the developer/CI venv matching the lock — enforcing
that is the gate's job, not the test suite's.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_lock_parity.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import check_lock_parity  # noqa: E402


def write_lock(path: Path, contents: str) -> Path:
    path.write_text(contents, encoding="utf-8")
    return path


def test_load_lock_parses_pins_and_extras(tmp_path: Path) -> None:
    lock = write_lock(
        tmp_path / "requirements.lock",
        "alembic==1.20.0 \\\n"
        "    --hash=sha256:abc\n"
        "psycopg[binary]==3.3.4 \\\n"
        "    --hash=sha256:def\n",
    )

    pins = check_lock_parity.load_lock(lock)

    assert pins["alembic"].version == "1.20.0"
    assert pins["psycopg"].version == "3.3.4"


def test_matching_lock_passes(tmp_path: Path, monkeypatch, capsys) -> None:
    lock = write_lock(tmp_path / "requirements.lock", "alembic==1.20.0\n")
    monkeypatch.setattr(
        check_lock_parity,
        "installed_version",
        lambda name: {"alembic": "1.20.0"}.get(name),
    )

    exit_code = check_lock_parity.main(["--lock", str(lock)])

    assert exit_code == 0
    assert "[lock-parity] OK" in capsys.readouterr().out


def test_version_drift_fails_and_names_the_package(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    lock = write_lock(tmp_path / "requirements.lock", "alembic==0.0.1\n")
    monkeypatch.setattr(
        check_lock_parity,
        "installed_version",
        lambda name: {"alembic": "1.20.0"}.get(name),
    )

    exit_code = check_lock_parity.main(["--lock", str(lock)])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "alembic" in output
    assert "version mismatch" in output
