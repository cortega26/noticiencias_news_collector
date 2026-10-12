from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "run_collector_smoke.py"
SPEC = importlib.util.spec_from_file_location("run_collector_smoke", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _isolated_smoke_environment(tmp_path: Path) -> dict[str, str]:
    """Keep smoke subprocess files and database inside pytest's temp directory."""
    env = os.environ.copy()
    env.update(
        {
            "NOTICIENCIAS_SMOKE": "1",
            "NOTICIENCIAS__DATABASE__PATH": str(tmp_path / "smoke.db"),
            "NOTICIENCIAS__PATHS__DATA_DIR": str(tmp_path / "data"),
            "NOTICIENCIAS__PATHS__LOGS_DIR": str(tmp_path / "logs"),
            "NOTICIENCIAS__PATHS__DLQ_DIR": str(tmp_path / "dlq"),
        }
    )
    return env


def test_smoke_contract_requires_fixture_output() -> None:
    assert MODULE._smoke_contract_satisfied(
        {"sources_processed": 1, "articles_found": 1}
    )
    assert not MODULE._smoke_contract_satisfied(
        {"sources_processed": 1, "articles_found": 0}
    )


@pytest.mark.e2e
def test_run_collector_smoke_replay_contract(tmp_path: Path) -> None:
    env = _isolated_smoke_environment(tmp_path)

    result = subprocess.run(
        [sys.executable, "scripts/run_collector_smoke.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + "\n" + result.stderr

    smoke_payload_line = next(
        line
        for line in reversed(result.stdout.splitlines())
        if '"mode": "smoke"' in line
    )
    payload = json.loads(smoke_payload_line)
    assert payload["sources_processed"] == 1
    assert payload["articles_found"] >= 1


def test_run_collector_smoke_fails_if_fixture_missing(monkeypatch, tmp_path) -> None:
    missing_fixture = tmp_path / "missing_replay.jsonl"
    monkeypatch.setattr(MODULE, "SMOKE_FIXTURE_PATH", missing_fixture)
    monkeypatch.setenv("NOTICIENCIAS_SMOKE", "1")
    assert MODULE.main() == 1


@pytest.mark.e2e
def test_run_collector_smoke_network_tripwire(tmp_path: Path) -> None:

    # Run the smoke script in a SUBPROCESS with a prelude that patches
    # requests/httpx to deny ALL network calls BEFORE the script imports
    # the collector. Running in-process lets any earlier test's global
    # state (runtime config, RUNTIME, reloaded modules) leak into the
    # smoke's system initialization — pytest-randomly surfaced it by
    # shuffling order (2026-08-12). A clean process makes the tripwire
    # hermetic AND more faithful (it exercises the real CLI entry point).
    prelude = (
        "import requests, httpx, os, sys\n"
        "def _deny(*a, **k):\n"
        "    raise AssertionError('network call blocked in smoke')\n"
        "requests.get = requests.post = _deny\n"
        "httpx.get = httpx.post = _deny\n"
        "requests.sessions.Session.get = requests.sessions.Session.post = _deny\n"
        "httpx.Client.get = httpx.Client.post = _deny\n"
        f"__file__ = os.path.abspath({str(SCRIPT_PATH)!r})\n"
    )
    env = _isolated_smoke_environment(tmp_path)
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            prelude
            + "exec(open(__file__).read())\nimport run_collector_smoke as m\nsys.exit(m.main())",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = proc.stdout + proc.stderr
    if proc.returncode != 0:
        print("\n=== STDOUT ===\n", proc.stdout)
        print("\n=== STDERR ===\n", proc.stderr)
    assert proc.returncode == 0, f"Smoke main failed with exit code {proc.returncode}"
    assert "network call blocked" not in out, f"Unexpected network call: {out}"
    assert '"mode": "smoke"' in out, f"Smoke payload missing: {out}"
