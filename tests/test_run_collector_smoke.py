from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import requests

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "run_collector_smoke.py"
SPEC = importlib.util.spec_from_file_location("run_collector_smoke", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_smoke_contract_requires_fixture_output() -> None:
    assert MODULE._smoke_contract_satisfied(
        {"sources_processed": 1, "articles_found": 1}
    )
    assert not MODULE._smoke_contract_satisfied(
        {"sources_processed": 1, "articles_found": 0}
    )


def test_run_collector_smoke_replay_contract() -> None:
    env = os.environ.copy()
    env["NOTICIENCIAS_SMOKE"] = "1"

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
    assert MODULE.main() == 1


def test_run_collector_smoke_network_tripwire(capfd, monkeypatch) -> None:
    def _deny_network(*args, **kwargs):  # noqa: ARG001
        msg = f"External network call attempted in smoke mode: {args} {kwargs}"
        import traceback
        traceback.print_stack()
        print(msg)
        raise AssertionError(msg)

    monkeypatch.setenv("NOTICIENCIAS_SMOKE", "1")
    monkeypatch.setattr(requests, "get", _deny_network)
    monkeypatch.setattr(requests, "post", _deny_network)
    monkeypatch.setattr(requests.sessions.Session, "get", _deny_network)
    monkeypatch.setattr(requests.sessions.Session, "post", _deny_network)
    monkeypatch.setattr(httpx, "get", _deny_network)
    monkeypatch.setattr(httpx, "post", _deny_network)
    monkeypatch.setattr(httpx.Client, "get", _deny_network)
    monkeypatch.setattr(httpx.Client, "post", _deny_network)

    result = MODULE.main()
    if result != 0:
        out, err = capfd.readouterr()
        print("\n=== STDOUT ==\n", out)
        print("\n=== STDERR ==\n", err)
        assert result == 0, f"Smoke main failed with exit code {result}"
