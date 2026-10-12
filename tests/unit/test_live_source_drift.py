from __future__ import annotations

import json

from news_collector.contracts.source_health import SourceHealthRecord
from news_collector.logic.workflows.live_source_drift import (
    _load_health_records,
    build_live_source_drift_report,
    load_source_health_file,
    render_live_source_drift_markdown,
)


def _record(source_id: str, **overrides: object) -> SourceHealthRecord:
    payload = {
        "source_id": source_id,
        "content_mode": "full_text",
        "enrichment_strategy": "scrapling_stealth",
        "feed_ok": True,
        "pipeline_ok": True,
        "content_ok": True,
        "articles_found": 5,
        "articles_saved": 5,
        "save_ratio": 1.0,
        "total_enrichment_attempted": 5,
        "total_publishable": 5,
        "publishable_ratio": 1.0,
        "plain_http_attempts": 1,
        "plain_http_success": 0,
        "plain_http_success_rate": 0.0,
        "scrapling_http_attempts": 5,
        "scrapling_http_success": 5,
        "scrapling_http_success_rate": 1.0,
        "scrapling_stealth_attempts": 5,
        "scrapling_stealth_success": 3,
        "scrapling_stealth_success_rate": 0.6,
        "headless_seconds_used": 12.0,
        "operational_state": "healthy_full_text",
    }
    payload.update(overrides)
    return SourceHealthRecord.model_validate(payload)


def test_build_live_source_drift_report_flags_new_failures_and_strategy_mismatch() -> (
    None
):
    baseline = {
        "phys_org": _record("phys_org"),
    }
    current = {
        "phys_org": _record(
            "phys_org",
            articles_saved=0,
            save_ratio=0.0,
            total_publishable=0,
            publishable_ratio=0.0,
            content_ok=False,
            operational_state="failing_suppressed_candidate",
            failure_taxonomy="anti_bot_block",
        ),
    }

    report = build_live_source_drift_report(
        current_records=current,
        baseline_records=baseline,
        monitored_sources=["phys_org"],
    )

    assert report["summary"]["newly_broken_count"] == 1
    assert report["summary"]["save_ratio_collapse_count"] == 1
    assert report["summary"]["publishability_collapse_count"] == 1
    assert report["summary"]["strategy_mismatch_count"] == 1
    assert report["newly_broken"][0]["source_id"] == "phys_org"
    assert report["strategy_mismatch"][0]["recommendation"] == "prefer_scrapling_http"


def test_build_live_source_drift_report_flags_handoff_regressions() -> None:
    current = {
        "openai_blog": _record(
            "openai_blog",
            failure_taxonomy="publication_contract_failure",
            last_error_message="validate:content permalink mismatch",
        ),
    }

    report = build_live_source_drift_report(
        current_records=current,
        baseline_records={},
        monitored_sources=["openai_blog"],
    )

    assert report["summary"]["handoff_regression_count"] == 1
    assert report["handoff_regressions"][0]["source_id"] == "openai_blog"


def test_render_live_source_drift_markdown_is_stable() -> None:
    report = build_live_source_drift_report(
        current_records={"reddit_science": _record("reddit_science")},
        baseline_records={},
        monitored_sources=["reddit_science"],
    )

    markdown = render_live_source_drift_markdown(report)

    assert markdown.startswith("# Live Source Drift Report")
    assert "## Strategy Mismatch" in markdown
    assert "`reddit_science`" in markdown


def test_load_health_records_stamps_source_id_and_skips_non_mappings() -> None:
    raw_valid = _record("phys_org").model_dump()
    raw_valid.pop("source_id")  # file key must stamp it via the helper

    records = _load_health_records(
        {"phys_org": raw_valid, "junk": "not-a-mapping", "empty": 42}
    )

    assert set(records) == {"phys_org"}
    assert records["phys_org"].source_id == "phys_org"


def test_load_source_health_file_handles_missing_and_invalid(tmp_path) -> None:
    assert load_source_health_file(None) == {}
    assert load_source_health_file(tmp_path / "absent.json") == {}

    not_mapping = tmp_path / "list.json"
    not_mapping.write_text(json.dumps(["nope"]), encoding="utf-8")
    assert load_source_health_file(not_mapping) == {}


def test_load_source_health_file_loads_valid_payload(tmp_path) -> None:
    raw = _record("phys_org").model_dump()
    path = tmp_path / "health.json"
    path.write_text(json.dumps({"phys_org": raw}), encoding="utf-8")

    records = load_source_health_file(path)

    assert set(records) == {"phys_org"}
    assert records["phys_org"].source_id == "phys_org"


def test_build_report_flags_plain_http_upgrade_and_headless_budget() -> None:
    current = {
        "plain_source": _record(
            "plain_source",
            enrichment_strategy="http",
            failure_taxonomy="js_render_required",
        ),
        "stalled_source": _record(
            "stalled_source",
            enrichment_strategy="http",
            content_mode="summary_only",
            headless_seconds_used=5.0,
            articles_saved=0,
        ),
    }

    report = build_live_source_drift_report(
        current_records=current,
        baseline_records={},
        monitored_sources=["plain_source", "stalled_source"],
    )

    recommendations = {
        entry["source_id"]: entry["recommendation"]
        for entry in report["strategy_mismatch"]
    }
    assert recommendations["plain_source"] == "upgrade_from_plain_http"
    assert recommendations["stalled_source"] == "remove_headless_budget"


def test_build_report_skips_unmonitored_absent_sources() -> None:
    report = build_live_source_drift_report(
        current_records={},
        baseline_records={},
        monitored_sources=["ghost_source"],
    )

    assert report["summary"]["sources_evaluated"] == 1
    assert report["newly_broken"] == []
