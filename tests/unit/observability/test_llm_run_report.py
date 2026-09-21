"""Per-run LLM health report: stage counters, aggregation, alerting, fail-open."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from news_collector.infrastructure.llm import attempts
from news_collector.infrastructure.llm.failure_kinds import FailureKind
from news_collector.observability import llm_run_report as rr
from news_collector.observability import llm_run_stats
from news_collector.observability.llm_metrics_store import (
    LLMMetricsStore,
    ProviderSummary,
)
from news_collector.scoring.pre_scorer import PreScorer


@pytest.fixture(autouse=True)
def _clean_stats():
    llm_run_stats.reset()
    yield
    llm_run_stats.reset()


def _provider(purpose="scoring", calls=4, ok=4):
    return ProviderSummary("groq", "m", purpose, calls=calls, ok=ok)


# ------------------------------------------------------------------- counters


def test_stats_record_snapshot_reset_and_ignore_non_positive():
    llm_run_stats.record("scoring", "llm", 3)
    llm_run_stats.record("scoring", "llm")
    llm_run_stats.record("scoring", "heuristic.chunk_failed", 0)
    llm_run_stats.record("scoring", "heuristic.chunk_failed", -2)
    assert llm_run_stats.snapshot() == {"scoring.llm": 4}
    llm_run_stats.reset()
    assert llm_run_stats.snapshot() == {}


# ---------------------------------------------------------------- aggregation


def test_build_report_healthy_run():
    counts = {"prescoring.llm": 40, "scoring.llm": 18, "scoring.cached": 5}
    report = rr.build_run_report(counts, [_provider()], run_id="r1")
    assert report.degraded is False and report.reasons == []
    scoring = next(s for s in report.stages if s.stage == "scoring")
    assert (scoring.llm, scoring.cached, scoring.total) == (18, 5, 23)
    assert scoring.heuristic_ratio == 0.0


def test_build_report_flags_heuristic_ratio_with_main_reason():
    counts = {
        "scoring.llm": 4,
        "scoring.heuristic.chunk_failed": 12,
        "scoring.heuristic.llm_unavailable": 4,
    }
    report = rr.build_run_report(counts, [_provider()], warn_heuristic_ratio=0.5)
    assert report.degraded is True
    assert "scoring: 80%" in report.reasons[0] and "chunk_failed" in report.reasons[0]


def test_build_report_threshold_is_respected():
    counts = {"prescoring.llm": 6, "prescoring.heuristic.filled": 4}  # 40%
    assert (
        rr.build_run_report(
            counts, [_provider("prescoring")], warn_heuristic_ratio=0.5
        ).degraded
        is False
    )
    assert (
        rr.build_run_report(
            counts, [_provider("prescoring")], warn_heuristic_ratio=0.3
        ).degraded
        is True
    )


def test_build_report_flags_a_purpose_where_every_attempt_failed():
    report = rr.build_run_report({}, [_provider("scoring", calls=3, ok=0)])
    assert (
        report.degraded
        and "scoring: every provider attempt failed" in report.reasons[0]
    )


def test_no_llm_activity_never_alerts():
    """CI (no keys): everything is heuristic, which is expected, not an alarm."""
    counts = {"scoring.heuristic.llm_unavailable": 50}
    report = rr.build_run_report(counts, [])
    assert report.llm_activity is False and report.degraded is False
    assert "Sin actividad de LLM" in rr.format_run_report(report)


def test_format_and_as_dict_and_write(tmp_path):
    counts = {"prescoring.llm": 20, "prescoring.heuristic.filled": 5, "scoring.llm": 10}
    report = rr.build_run_report(counts, [_provider()], run_id="r9")
    text = rr.format_run_report(report)
    assert "prescoring" in text and "LLM saludable" in text and "groq" in text
    degraded = rr.build_run_report(
        {"scoring.llm": 1, "scoring.heuristic.x": 9}, [_provider()]
    )
    assert "DEGRADADO" in rr.format_run_report(degraded)

    data = report.as_dict()
    assert data["run_id"] == "r9" and data["stages"][0]["total"] == 25
    path = rr.write_run_report(report, tmp_path / "sub" / "r.json")
    assert json.loads(path.read_text())["degraded"] is False
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert rr.write_run_report(report, blocker / "x.json") is None  # fail-open


# ---------------------------------------------------------- store run_id filter


def test_store_summary_filters_by_run_id(tmp_path, monkeypatch):
    from news_collector.observability import llm_metrics_store as ms

    store = LLMMetricsStore(tmp_path / "m.db", environment="t")

    def rec(run):
        monkeypatch.setattr(
            ms.run_context, "get_context", lambda: {"run_id": run, "environment": "t"}
        )
        store.record(
            attempts.AttemptRecord(
                "groq", "m", "scoring", True, None, 100, 0, ts=time.time()
            )
        )

    rec("run-a"), rec("run-a"), rec("run-b")
    assert store.summary(run_id="run-a")[0].calls == 2
    assert store.summary(run_id="run-b")[0].calls == 1
    assert store.summary()[0].calls == 3


# ------------------------------------------------------------------ emit / wiring


def _cfg(enabled=True, ratio=0.5):
    return SimpleNamespace(
        llm_health=SimpleNamespace(enabled=enabled, warn_heuristic_ratio=ratio)
    )


class _Store:
    def __init__(self, rows):
        self.rows = rows
        self.run_id = None

    def summary(self, by_purpose=False, run_id=None, since_ts=None):
        self.run_id = run_id
        self.since_ts = since_ts
        return self.rows


def test_emit_prints_exports_and_scopes_the_store_to_this_run(tmp_path):
    llm_run_stats.record("scoring", "llm", 8)
    out: list[str] = []
    store = _Store([_provider()])
    report = rr.emit_run_report(
        _cfg(), emit=out.append, export_path=tmp_path / "r.json", store=store
    )
    assert report and "LLM saludable" in out[0] and (tmp_path / "r.json").exists()
    assert store.run_id  # filtered to the current run


def test_emit_logs_a_degraded_event_exports_and_can_be_disabled(tmp_path, monkeypatch):
    llm_run_stats.record("scoring", "llm", 1)
    llm_run_stats.record("scoring", "heuristic.chunk_failed", 9)
    seen: list = []
    import news_collector.utils.logger as logmod

    class _L:
        def warning(self, msg, *a, **_k):
            seen.append(msg)

    monkeypatch.setattr(
        logmod,
        "get_logger",
        lambda: SimpleNamespace(create_module_logger=lambda *_a, **_k: _L()),
    )
    out: list[str] = []
    target = tmp_path / "degraded.json"
    store = _Store([_provider()])
    report = rr.emit_run_report(
        _cfg(), emit=out.append, export_path=target, store=store
    )

    assert report.degraded and "DEGRADADO" in out[0]
    (event,) = [m for m in seen if isinstance(m, dict)]
    assert event["event"] == "llm.run.degraded"
    assert event["run_id"] == report.run_id and event["reasons"] == report.reasons
    assert (
        json.loads(target.read_text(encoding="utf-8"))["degraded"] is True
    )  # exported
    # healthy run: no degraded event, no export without a path
    seen.clear()
    llm_run_stats.reset()
    llm_run_stats.record("scoring", "llm", 5)
    ok = rr.emit_run_report(
        _cfg(), emit=out.append, export_path=None, store=_Store([_provider()])
    )
    assert ok.degraded is False and not [m for m in seen if isinstance(m, dict)]
    # disabled: nothing printed, store never queried
    printed = len(out)
    untouched = _Store([])
    assert (
        rr.emit_run_report(_cfg(enabled=False), emit=out.append, store=untouched)
        is None
    )
    assert (
        len(out) == printed
        and untouched.run_id is None
        and not hasattr(untouched, "since_ts")
    )


def test_emit_uses_the_configured_threshold_and_scope_window(tmp_path):
    llm_run_stats.record("scoring", "llm", 3)
    llm_run_stats.record("scoring", "heuristic.chunk_failed", 5)  # 62.5 % heuristic
    strict = rr.emit_run_report(
        _cfg(ratio=0.5), emit=lambda _t: None, store=_Store([_provider()])
    )
    lax = rr.emit_run_report(
        _cfg(ratio=0.9), emit=lambda _t: None, store=_Store([_provider()])
    )
    assert strict.degraded is True and lax.degraded is False
    scope = llm_run_stats.begin_scope()
    store = _Store([_provider()])
    scoped = rr.emit_run_report(_cfg(), emit=lambda _t: None, store=store, scope=scope)
    assert store.since_ts == scope.started_at
    assert all(
        s.total == 0 for s in scoped.stages
    )  # counters from before the scope are excluded


def test_emit_is_fail_open():
    class Boom:
        def summary(self, **_k):
            raise RuntimeError("db exploded")

    assert (
        rr.emit_run_report(_cfg(), emit=lambda _t: None, export_path=None, store=Boom())
        is None
    )


# -------------------------------------------------------- stage instrumentation


def _candidates(n=8):
    return [
        {"title": f"Title {i}", "summary": "s" * 40, "url": f"https://x.test/{i}"}
        for i in range(n)
    ]


def test_prescorer_records_llm_partial_and_filled(monkeypatch):
    llm = MagicMock(model="m")
    llm.generate_sync.return_value = {"selected_indices": [1, 2]}
    PreScorer(llm_client=llm).select_top_candidates(_candidates(), limit=4)
    assert llm_run_stats.snapshot() == {
        "prescoring.llm": 2,
        "prescoring.heuristic.filled": 2,
    }


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        ("LLM System is marked as unavailable (Disabled).", "unavailable"),
        ("circuit breaker is open", "rate_limited"),
        ("boom", "error"),
    ],
)
def test_prescorer_records_the_failure_reason(error, reason):
    llm = MagicMock(model="m")
    llm.generate_sync.side_effect = RuntimeError(error)
    PreScorer(llm_client=llm).select_top_candidates(_candidates(), limit=3)
    assert llm_run_stats.snapshot() == {f"prescoring.heuristic.{reason}": 3}


def test_prescorer_records_open_breaker(monkeypatch):
    from news_collector.infrastructure.llm.rate_limiter import LLMRateLimiter

    fake = SimpleNamespace(circuit_breaker=SimpleNamespace(is_open=True))
    monkeypatch.setattr(LLMRateLimiter, "get_instance", staticmethod(lambda: fake))
    PreScorer(llm_client=MagicMock(model="m")).select_top_candidates(
        _candidates(), limit=3
    )
    assert llm_run_stats.snapshot() == {"prescoring.heuristic.breaker_open": 3}


def test_failure_kinds_import_is_stable():
    assert FailureKind.TIMEOUT.value == "timeout"


# ------------------------------------------------ review follow-ups (PR #284)


def test_scope_limits_counters_and_store_query_to_one_workflow(tmp_path):
    llm_run_stats.record("scoring", "llm", 50)  # an earlier publication
    scope = llm_run_stats.begin_scope()
    llm_run_stats.record("scoring", "llm", 3)
    llm_run_stats.record("scoring", "heuristic.chunk_failed", 1)
    assert llm_run_stats.delta_since(scope) == {
        "scoring.llm": 3,
        "scoring.heuristic.chunk_failed": 1,
    }

    store = _Store([_provider()])
    out: list[str] = []
    report = rr.emit_run_report(
        _cfg(), emit=out.append, export_path=None, store=store, scope=scope
    )
    scoring = next(s for s in report.stages if s.stage == "scoring")
    assert (scoring.llm, scoring.heuristic) == (3, 1)  # not the cumulative 53
    assert store.since_ts == scope.started_at


def test_total_provider_outage_is_reported_not_hidden():
    """Every provider skipped (circuit open/cooldown): 0 calls but not 'no activity'."""
    outage = ProviderSummary("groq", "m", "scoring", calls=0, ok=0, skips=6)
    counts = {"scoring.heuristic.llm_unavailable": 40}
    report = rr.build_run_report(counts, [outage])
    assert report.llm_activity is True and report.degraded is True
    assert any("all providers unavailable" in r for r in report.reasons)
    assert "Sin actividad" not in rr.format_run_report(report)


def test_record_failure_is_logged_once_with_context(monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(llm_run_stats, "_RECORD_ERROR_LOGGED", False)
    monkeypatch.setattr(
        llm_run_stats.logger,
        "warning",
        lambda msg, *a, **_k: warnings.append(msg.format(*a)),
    )

    class _BadLock:
        def __enter__(self):
            raise RuntimeError("lock broken")

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(llm_run_stats, "_LOCK", _BadLock())
    llm_run_stats.record("scoring", "llm", 2)
    llm_run_stats.record("scoring", "llm", 2)
    assert (
        len(warnings) == 1
        and "scoring.llm" in warnings[0]
        and "lock broken" in warnings[0]
    )


def test_rescoring_stage_is_informational_and_never_alerts():
    from news_collector.observability import llm_run_report as r

    assert "rescoring" in r.STAGES
    assert "rescoring" not in r.ALERTING_STAGES


def test_rescore_only_report_still_shows_the_rescoring_row():
    from news_collector.observability import llm_run_report as r

    rep = r.LLMRunReport(
        run_id="x",
        stages=[
            r.StageOutcome(
                stage="rescoring",
                llm=0,
                cached=0,
                heuristic=5,
                heuristic_reasons={"no_llm_by_policy": 5},
            )
        ],
        providers=[],
        degraded=False,
        reasons=[],
        llm_activity=False,
    )
    text = r.format_run_report(rep)
    assert "rescoring" in text and "no_llm_by_policy=5" in text
