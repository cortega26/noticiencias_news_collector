"""LLM metrics store: persistence, aggregation, fail-open, sink wiring, report."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from news_collector.infrastructure.llm import attempts
from news_collector.infrastructure.llm.factory import FallbackProvider
from news_collector.infrastructure.llm.failure_kinds import FailureKind
from news_collector.observability import llm_metrics_store as store_mod
from news_collector.observability.llm_metrics_store import (
    LLMMetricsStore,
    _percentile,
    format_report,
)


def _rec(
    provider="nvidia", ok=True, kind=None, latency=1000, index=0, purpose="scoring"
):
    return attempts.AttemptRecord(
        provider=provider,
        model=f"{provider}-model",
        purpose=purpose,
        ok=ok,
        kind=kind,
        latency_ms=latency,
        failover_index=index,
        error=None if ok else "boom",
        ts=time.time(),
    )


@pytest.fixture
def store(tmp_path):
    return LLMMetricsStore(tmp_path / "m" / "llm.db", environment="test")


def test_percentile_nearest_rank():
    assert _percentile([], 50) is None
    assert _percentile([10], 95) == 10
    assert _percentile(list(range(1, 101)), 50) == 50
    assert _percentile(list(range(1, 101)), 95) == 95


def test_record_and_summary_aggregation(store):
    for latency in (1000, 2000, 3000, 4000):
        store.record(_rec(latency=latency))
    store.record(_rec(ok=False, kind=FailureKind.HTTP_5XX, latency=500))
    store.record(_rec(ok=False, kind=FailureKind.EMPTY_RESPONSE))
    store.record(_rec(ok=False, kind=FailureKind.INVALID_JSON))
    store.record(_rec(ok=False, kind=FailureKind.DEGRADED_SKIP, latency=0))
    store.record(_rec(provider="groq", index=1, latency=800))

    by_provider = {s.provider: s for s in store.summary()}
    nv = by_provider["nvidia"]
    assert (nv.calls, nv.ok, nv.skips, nv.blank) == (7, 4, 1, 2)
    assert nv.kinds == {"http_5xx": 1, "empty_response": 1, "invalid_json": 1}
    assert nv.p50_ms == 2000 and nv.p95_ms == 4000
    assert nv.success_rate == pytest.approx(4 / 7)
    assert nv.blank_rate == pytest.approx(2 / 7)
    groq = by_provider["groq"]
    assert groq.saves == 1 and groq.calls == 1
    assert nv.as_dict()["kinds"]["http_5xx"] == 1


def test_summary_by_purpose_and_window(store):
    store.record(_rec(purpose="scoring"))
    store.record(_rec(purpose="headline"))
    rows = store.summary(by_purpose=True)
    assert {r.purpose for r in rows} == {"scoring", "headline"}
    assert store.summary(since_ts=time.time() + 60) == []


def test_run_id_and_environment_are_stored(store):
    store.record(_rec())
    with sqlite3.connect(store.db_path) as conn:
        run_id, env = conn.execute(
            "SELECT run_id, environment FROM llm_calls"
        ).fetchone()
    assert run_id and env == "test"


def test_concurrent_writers_do_not_lose_rows(store):
    def worker():
        for _ in range(25):
            store.record(_rec())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert store.summary()[0].calls == 200
    assert store.failed_writes == 0


def test_retention_purges_old_rows(tmp_path):
    db = tmp_path / "llm.db"
    first = LLMMetricsStore(db, environment="test", retention_days=90)
    old = _rec()
    first.record(
        attempts.AttemptRecord(**{**old.__dict__, "ts": time.time() - 200 * 86400})
    )
    first.record(_rec())
    reopened = LLMMetricsStore(db, environment="test", retention_days=90)
    assert reopened.summary()[0].calls == 1


def test_store_is_fail_open_when_path_unusable(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    broken = LLMMetricsStore(blocker / "sub" / "llm.db", environment="test")
    broken.record(_rec())  # must not raise
    broken.record(_rec())
    assert broken.failed_writes >= 2
    assert broken.summary() == []


def test_store_survives_runtime_sql_errors(store, monkeypatch):
    def boom():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store, "_connect", boom)
    store.record(_rec())
    assert store.failed_writes == 1
    assert store.summary() == []


def test_fallback_chain_feeds_the_store_end_to_end(store):
    class P:
        def __init__(self, name, out):
            self.name, self.model, self.timeout, self.out = name, f"{name}-m", 60, out

        def generate_sync(self, **_kw):
            if isinstance(self.out, BaseException):
                raise self.out
            return self.out

    attempts.reset_state()
    attempts.register_attempt_sink(store.record)
    try:
        chain = FallbackProvider(
            [P("a", RuntimeError("down")), P("b", "answer")], purpose="headline"
        )
        assert chain.generate_sync("p") == "answer"
    finally:
        attempts.unregister_attempt_sink(store.record)
        attempts.reset_state()
    rows = {r.provider: r for r in store.summary(by_purpose=True)}
    assert rows["a"].kinds == {"unknown": 1} and rows["a"].purpose == "headline"
    assert rows["b"].saves == 1


def test_install_default_sink_respects_env_and_pytest(monkeypatch):
    # Under pytest the sink is never installed.
    assert store_mod.install_default_metrics_sink() is None
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("NOTICIENCIAS_LLM_METRICS", "0")
    assert store_mod.install_default_metrics_sink() is None


def test_install_default_sink_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("NOTICIENCIAS_LLM_METRICS", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(store_mod, "_default_store", None)
    first = store_mod.install_default_metrics_sink()
    try:
        assert first is not None and store_mod.install_default_metrics_sink() is first
        assert (tmp_path / "data" / "metrics").exists()
    finally:
        attempts.unregister_attempt_sink(first.record)


def test_format_report(store):
    assert "No LLM attempts" in format_report([])
    store.record(_rec(latency=1500))
    store.record(_rec(ok=False, kind=FailureKind.TIMEOUT))
    text = format_report(store.summary())
    assert "nvidia" in text and "timeout=1" in text and "1.5s" in text


def _load_script():
    path = Path(__file__).resolve().parents[3] / "scripts" / "llm_health_report.py"
    spec = importlib.util.spec_from_file_location("llm_health_report", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_report_script_text_json_and_probe(store, capsys, monkeypatch):
    store.record(_rec())
    script = _load_script()
    assert script.main(["--db", str(store.db_path), "--days", "1"]) == 0
    assert "nvidia" in capsys.readouterr().out
    assert script.main(["--db", str(store.db_path), "--json", "--by-purpose"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["purpose"] == "scoring"

    class OK:
        model = "m"
        name = "ok"

        def check_health(self, _t):
            return True, "ok"

    class Bad(OK):
        name = "bad"

        def check_health(self, _t):
            raise RuntimeError("unreachable")

    import news_collector.infrastructure.llm.factory as factory

    monkeypatch.setattr(
        factory, "get_provider", lambda **_k: FallbackProvider([OK(), Bad()])
    )
    assert script.main(["--probe"]) == 1
    out = capsys.readouterr().out
    assert "OK " in out and "FAIL" in out and "unreachable" in out
