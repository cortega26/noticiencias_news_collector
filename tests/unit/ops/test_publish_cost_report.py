"""Unit tests for scripts/ops/publish_cost_report.py (Plan 107).

Pure aggregation over fixture attempts files: no DB, no network, no
production data. Fixtures live in tmp_path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

OPS_DIR = Path(__file__).resolve().parents[3] / "scripts" / "ops"
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from publish_cost_report import (  # noqa: E402
    build_report,
    load_attempts,
    load_source_states,
    main,
)


def _write_attempt(
    tmp: Path, name: str, *, success: bool, failure_class=None, stages=None
) -> None:
    payload = {
        "schema_version": 1,
        "article_id": name,
        "success": success,
        "failure_class": failure_class,
        "stages": stages or [],
    }
    (tmp / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")


def _ok_stages() -> list[dict]:
    return [
        {"name": "identity_resolved", "success": True, "details": {}},
        {"name": "editor_refinement", "success": True, "details": {}},
        {
            "name": "editorial_critic",
            "success": True,
            "details": {"average": 8.0},
        },
        {
            "name": "readability",
            "success": True,
            "details": {"words": 1000},
        },
        {"name": "pr_created", "success": True, "details": {}},
    ]


def test_full_success_article(tmp_path: Path) -> None:
    _write_attempt(tmp_path, "1", success=True, stages=_ok_stages())
    costs, bad = load_attempts(tmp_path)
    assert bad == 0 and len(costs) == 1
    (cost,) = costs
    assert cost.success is True
    assert cost.failure_class is None
    assert cost.critic_average == 8.0
    assert cost.words == 1000
    # draft(1) + critic(2) per CALL_MODEL.
    assert cost.estimated_calls_metered_part == 3


def test_failed_article_counts_failure_class_and_stage(tmp_path: Path) -> None:
    _write_attempt(
        tmp_path,
        "2",
        success=False,
        failure_class="editorial_fact_check_disputed",
        stages=[
            {"name": "identity_resolved", "success": True, "details": {}},
            {"name": "policy_gate", "success": False, "details": {}},
        ],
    )
    costs, _ = load_attempts(tmp_path)
    report = build_report(costs, 0, {})
    assert report.succeeded == 0
    assert report.failure_classes == {"editorial_fact_check_disputed": 1}
    assert report.stage_failures == {"policy_gate": 1}
    assert report.critic_average_mean is None


def test_frontend_validation_sidecars_and_garbage_are_skipped(tmp_path: Path) -> None:
    _write_attempt(tmp_path, "3", success=True, stages=_ok_stages())
    (tmp_path / "3.frontend_validation.json").write_text("{}", encoding="utf-8")
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    costs, bad = load_attempts(tmp_path)
    assert len(costs) == 1 and bad == 1


def test_missing_attempts_dir_is_exit_2(tmp_path: Path) -> None:
    assert main(["--attempts-dir", str(tmp_path / "nope")]) == 2


def test_aggregate_math_and_assumptions(tmp_path: Path) -> None:
    _write_attempt(tmp_path, "1", success=True, stages=_ok_stages())
    _write_attempt(tmp_path, "2", success=True, stages=_ok_stages())
    costs, _ = load_attempts(tmp_path)
    report = build_report(costs, 0, {})
    assert report.attempts_total == 2
    assert report.success_rate == 1.0
    assert report.estimated_calls_metered_total == 6
    assert report.estimated_calls_per_article_mean == 3.0
    assert report.nominal_unmetered_per_article_max == 11
    assert any("not model calls" in a for a in report.assumptions)


def test_source_states_roll_up(tmp_path: Path) -> None:
    health = tmp_path / "health.json"
    health.write_text(
        json.dumps(
            {
                "sources": {
                    "a": {"operational_state": "healthy_full_text"},
                    "b": {"operational_state": "failing_suppressed_candidate"},
                    "c": {"operational_state": "healthy_full_text"},
                }
            }
        ),
        encoding="utf-8",
    )
    states = load_source_states(health)
    costs, _ = load_attempts(tmp_path)
    report = build_report(costs, 0, states)
    assert report.sources_total == 3
    assert report.sources_by_state == {
        "failing_suppressed_candidate": 1,
        "healthy_full_text": 2,
    }


def test_missing_source_health_warns_and_continues(tmp_path: Path, caplog) -> None:
    states = load_source_states(tmp_path / "absent.json")
    assert len(states) == 0
