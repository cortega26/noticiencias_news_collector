from news_collector.contracts.source_health import SourceHealthRecord
from news_collector.system.source_health import (
    build_source_health_record,
    serialize_source_health_report,
)


def test_source_health_report_serialization_includes_all_configured_sources():
    source_configs = {
        "observed_source": {
            "name": "Observed Source",
            "language": "en",
            "content_mode": "summary_only",
            "enrichment_strategy": "scrapling_stealth",
        },
        "configured_only_source": {
            "name": "Configured Only Source",
            "language": "en",
            "content_mode": "full_text",
            "enrichment_strategy": "http",
        },
    }
    source_details = {
        "observed_source": {
            "feed_ok": True,
            "pipeline_ok": True,
            "content_ok": True,
            "articles_found": 4,
            "articles_saved": 3,
            "content_mode": "summary_only",
            "enrichment_strategy": "scrapling_stealth",
            "latency": 1.25,
            "last_error_message": None,
        }
    }
    metrics_by_source = {
        "observed_source": {
            "total_enrichment_attempted": 6,
            "total_publishable": 3,
            "avg_enrichment_time": 2.2,
            "avg_content_length": 850.0,
            "http_attempts": 1,
            "plain_http_attempts": 1,
            "plain_http_success": 1,
            "scrapling_http_attempts": 2,
            "scrapling_http_success": 1,
            "headless_attempts": 2,
            "scrapling_stealth_attempts": 2,
            "scrapling_stealth_success": 1,
            "proxy_attempts": 0,
            "scholarly_attempts": 0,
            "proxy_requests_used": 0,
            "headless_seconds_used": 9.4,
        }
    }

    report = serialize_source_health_report(
        source_details,
        source_configs=source_configs,
        metrics_by_source=metrics_by_source,
        last_run="2026-05-08T12:00:00Z",
    )

    assert set(report) == {"configured_only_source", "observed_source"}

    observed = SourceHealthRecord.model_validate(report["observed_source"])
    assert observed.operational_state == "healthy_summary_only"
    assert observed.failure_taxonomy is None
    assert observed.headless_seconds_used == 9.4
    assert observed.publishable_ratio == 0.5
    assert observed.save_ratio == 0.75
    assert observed.plain_http_success_rate == 1.0
    assert observed.scrapling_http_success_rate == 0.5
    assert observed.scrapling_stealth_success_rate == 0.5

    configured_only = SourceHealthRecord.model_validate(
        report["configured_only_source"]
    )
    assert configured_only.operational_state == "failing_suppressed_candidate"
    assert configured_only.articles_found == 0
    assert configured_only.articles_saved == 0
    assert configured_only.enrichment_strategy == "http"


def test_source_health_record_classifies_failures_deterministically():
    anti_bot = build_source_health_record(
        "blocked_source",
        source_config={"content_mode": "summary_only", "enrichment_strategy": "http"},
        observed={
            "feed_ok": True,
            "pipeline_ok": False,
            "content_ok": False,
            "articles_found": 2,
            "articles_saved": 0,
            "last_error_message": "Cloudflare blocked request",
        },
        metrics={},
    )
    assert anti_bot.failure_taxonomy == "anti_bot_block"
    assert anti_bot.operational_state == "partial_yield_flaky"

    publication_failure = build_source_health_record(
        "publish_failed_source",
        source_config={"content_mode": "full_text", "enrichment_strategy": "http"},
        observed={
            "feed_ok": True,
            "pipeline_ok": True,
            "content_ok": False,
            "articles_found": 1,
            "articles_saved": 0,
            "last_error_message": "validate:content duplicate permalink",
        },
        metrics={},
    )
    assert publication_failure.failure_taxonomy == "publication_contract_failure"
    assert publication_failure.operational_state == "partial_yield_flaky"
