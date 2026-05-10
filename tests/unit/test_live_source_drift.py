from __future__ import annotations

from news_collector.contracts.source_health import SourceHealthRecord
from news_collector.logic.workflows.live_source_drift import (
    build_live_source_drift_report,
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
