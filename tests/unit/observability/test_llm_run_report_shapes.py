"""Exact-output tests for observability.llm_run_report (mutation-driven).

The block printed at the end of every run and ``llm_run_report.json`` are what an operator reads to
decide whether the LLM chain is healthy: thresholds, wording anchors and JSON keys must not drift.
"""

from __future__ import annotations

import json

from news_collector.observability import llm_run_report as rr
from news_collector.observability.llm_metrics_store import ProviderSummary


def _p(purpose="scoring", calls=4, ok=4, skips=0):
    return ProviderSummary("groq", "m", purpose, calls=calls, ok=ok, skips=skips)


def test_stage_outcomes_accumulate_across_keys_and_reasons():
    stages = {
        s.stage: s
        for s in rr._stage_outcomes(
            {
                "scoring.llm": 3,
                "scoring.cached": 2,
                "scoring.heuristic.chunk_failed": 4,
                "scoring.heuristic.budget_exhausted": 1,
                "scoring.heuristic.chunk_failed.extra": 6,  # reason = everything after "heuristic."
                "prescoring.llm": 9,
                "other.llm": 100,  # not a known stage
            }
        )
    }
    scoring = stages["scoring"]
    assert (scoring.llm, scoring.cached, scoring.heuristic) == (3, 2, 11)
    assert scoring.heuristic_reasons == {
        "chunk_failed": 4,
        "chunk_failed.extra": 6,
        "budget_exhausted": 1,
    }
    assert stages["prescoring"].llm == 9 and stages["rescoring"].total == 0
    assert "other" not in stages


def test_stage_outcomes_sum_repeated_llm_and_cached_counts():
    # dict keys are unique, but two stages' counters must not bleed into each other
    stages = {
        s.stage: s for s in rr._stage_outcomes({"scoring.llm": 2, "rescoring.llm": 5})
    }
    assert stages["scoring"].llm == 2 and stages["rescoring"].llm == 5


def test_activity_thresholds():
    idle = rr.build_run_report({}, [_p(calls=0, ok=0)])
    assert idle.llm_activity is False and idle.degraded is False
    one_call = rr.build_run_report({}, [_p(calls=1, ok=1)])
    assert one_call.llm_activity is True
    one_skip = rr.build_run_report({}, [_p(calls=0, ok=0, skips=1)])
    assert one_skip.llm_activity is True
    llm_only = rr.build_run_report({"scoring.llm": 1}, [])
    assert llm_only.llm_activity is True


def test_outage_message_needs_zero_calls_and_at_least_one_skip():
    outage = rr.build_run_report({}, [_p(calls=0, ok=0, skips=1)])
    assert outage.degraded is True
    assert outage.reasons == [
        "all providers unavailable (every attempt was skipped: "
        "circuit open, cooling down or disabled)"
    ]
    mixed = rr.build_run_report({}, [_p(calls=2, ok=2, skips=3)])
    assert mixed.degraded is False  # some real calls happened
    assert rr.build_run_report({}, [_p(calls=0, ok=0, skips=0)]).reasons == []


def test_heuristic_ratio_threshold_is_strictly_greater_and_names_the_main_reason():
    counts = {"scoring.llm": 5, "scoring.heuristic.a": 3, "scoring.heuristic.b": 2}
    at_limit = rr.build_run_report(counts, [_p()], warn_heuristic_ratio=0.5)
    assert at_limit.degraded is False  # exactly 50 % is not "over"
    over = rr.build_run_report(counts, [_p()], warn_heuristic_ratio=0.49)
    assert over.reasons == [
        "scoring: 50% of items fell back to heuristics (main reason: a)"
    ]


def test_only_alerting_stages_raise_alerts():
    counts = {"rescoring.heuristic.no_llm_by_policy": 50, "scoring.llm": 1}
    assert rr.build_run_report(counts, [_p()]).degraded is False


def test_every_attempt_failed_is_reported_per_purpose_and_unlabelled_is_all():
    report = rr.build_run_report(
        {},
        [
            _p("prescoring", calls=3, ok=0),
            _p("scoring", calls=3, ok=3),
            _p("", calls=2, ok=0),
        ],
    )
    assert report.reasons == [
        "prescoring: every provider attempt failed",
        "all: every provider attempt failed",
    ]


def test_as_dict_shape_is_json_serializable_with_derived_fields():
    report = rr.build_run_report(
        {"scoring.llm": 1, "scoring.heuristic.chunk_failed": 3}, [_p()], run_id="r9"
    )
    d = report.as_dict()
    assert set(d) == {
        "run_id",
        "stages",
        "providers",
        "degraded",
        "reasons",
        "llm_activity",
    }
    assert d["run_id"] == "r9" and d["degraded"] is True and d["llm_activity"] is True
    scoring = next(s for s in d["stages"] if s["stage"] == "scoring")
    assert scoring["total"] == 4 and scoring["heuristic_ratio"] == 0.75
    assert scoring["heuristic_reasons"] == {"chunk_failed": 3}
    assert d["providers"][0]["provider"] == "groq"
    json.dumps(d)


def test_format_stage_line_is_exact():
    s = rr.StageOutcome(
        "scoring", llm=5, cached=2, heuristic=3, heuristic_reasons={"b": 1, "a": 2}
    )
    assert (
        rr._format_stage(s)
        == "scoring     LLM    5 | caché    2 | heurístico    3 (38%)  [a=2, b=1]"
    )
    empty = rr.StageOutcome("prescoring")
    assert (
        rr._format_stage(empty)
        == "prescoring  LLM    0 | caché    0 | heurístico    0  [-]"
    )


def test_format_run_report_no_activity_and_rescore_only():
    report = rr.build_run_report({}, [])
    assert rr.format_run_report(report).split("\n") == [
        "",
        "LLM DE ESTA CORRIDA:",
        "-" * 40,
        "Sin actividad de LLM (¿no configurado? scoring heurístico).",
    ]
    rescore = rr.build_run_report({"rescoring.heuristic.no_llm_by_policy": 5}, [])
    lines = rr.format_run_report(rescore).split("\n")
    assert lines[3].startswith("Sin actividad") and lines[4].startswith("rescoring")
    assert "no_llm_by_policy=5" in lines[4] and len(lines) == 5


def test_format_run_report_healthy_and_degraded_blocks():
    healthy = rr.build_run_report({"scoring.llm": 4}, [_p()])
    text = rr.format_run_report(healthy)
    lines = text.split("\n")
    assert lines[:3] == ["", "LLM DE ESTA CORRIDA:", "-" * 40]
    assert lines[3].startswith("scoring     LLM    4")
    assert "prescoring" not in text  # empty stages are not printed
    assert lines[-2] == "" and lines[-1] == "LLM saludable en esta corrida."

    degraded = rr.build_run_report({"scoring.heuristic.chunk_failed": 4}, [_p()])
    tail = rr.format_run_report(degraded).split("\n")
    assert tail[-2] == "" and tail[-1].startswith("DEGRADADO: scoring: 100% of items")
    assert "groq" in rr.format_run_report(degraded)  # provider table included


def test_write_run_report_creates_parents_and_is_fail_open(tmp_path):
    report = rr.build_run_report({"scoring.llm": 1}, [_p()], run_id="w")
    target = tmp_path / "deep" / "dir" / "r.json"
    assert rr.write_run_report(report, target) == target
    assert json.loads(target.read_text(encoding="utf-8"))["run_id"] == "w"
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert (
        rr.write_run_report(report, blocker / "child.json") is None
    )  # OSError -> None
