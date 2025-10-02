from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    config_file = tmp_path / "config.toml"
    if not config_file.exists():
        config_file.write_text("[news]\nmax_items = 10\n", encoding="utf-8")
    cmd = [
        sys.executable,
        "-m",
        "noticiencias.config_manager",
        "--config",
        str(config_file),
        *args,
    ]
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def test_validate_success(tmp_path: Path) -> None:
    result = _run_cli(tmp_path, "--validate")
    assert result.returncode == 0
    assert "Configuration OK" in result.stdout


def test_explain_reports_source(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("NOTICIENCIAS__NEWS__MAX_ITEMS=20\n", encoding="utf-8")
    result = _run_cli(tmp_path, "--explain", "news.max_items")
    assert result.returncode == 0
    assert "news.max_items" in result.stdout
    assert "NOTICIENCIAS__NEWS__MAX_ITEMS" in result.stdout


def test_set_updates_file_and_creates_backup(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        "[collection]\nrequest_timeout_seconds = 10\n", encoding="utf-8"
    )
    result = _run_cli(tmp_path, "--set", "collection.request_timeout_seconds=45")
    assert result.returncode == 0
    assert "collection.request_timeout_seconds" in result.stdout
    data = config_file.read_text(encoding="utf-8")
    assert "request_timeout_seconds = 45" in data
    backups = list((tmp_path / "backups").glob("config.toml.*.bak"))
    assert backups, "CLI updates must generate backups"


def test_validate_failure_reports_error(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        "[collection]\nrequest_timeout_seconds = 'oops'\n", encoding="utf-8"
    )
    result = _run_cli(tmp_path, "--validate")
    assert result.returncode == 1
    assert "collection.request_timeout_seconds" in result.stderr
    assert "file" in result.stderr
