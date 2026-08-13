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

SMOKE_ARTICLE_URL = "https://example.com/articles/smoke-article-1"


def _clean_smoke_article() -> None:
    """Remove the known smoke article URL from the database so the replay
    dedup check (article_exists) won't filter it out."""
    try:
        from news_collector.storage.database import get_database_manager

        db = get_database_manager()
        article = db.get_article_by_url(SMOKE_ARTICLE_URL)
        if article is not None:
            db.delete_article(article.id)
    except Exception:
        pass  # Non-fatal — the smoke test will fail independently if this matters


def test_smoke_contract_requires_fixture_output() -> None:
    assert MODULE._smoke_contract_satisfied(
        {"sources_processed": 1, "articles_found": 1}
    )
    assert not MODULE._smoke_contract_satisfied(
        {"sources_processed": 1, "articles_found": 0}
    )


def test_run_collector_smoke_replay_contract() -> None:
    _clean_smoke_article()
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
    monkeypatch.setenv("NOTICIENCIAS_SMOKE", "1")
    assert MODULE.main() == 1


def test_run_collector_smoke_network_tripwire() -> None:
    _clean_smoke_article()

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
    env = dict(os.environ)
    env["NOTICIENCIAS_SMOKE"] = "1"
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
