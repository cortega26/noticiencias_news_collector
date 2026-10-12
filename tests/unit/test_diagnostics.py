import json
from pathlib import Path
from unittest.mock import patch

from news_collector.contracts.source_health import SourceHealthRecord
from news_collector.diagnostics import SourceHealth, SourceHealthTracker


def test_source_health_update():
    sh = SourceHealth(source_id="test")
    sh.mark_stage_success("fetch", 5)
    assert sh.fetch_ok == 5

    sh.mark_stage_success("parse", 2)
    assert sh.parsed_ok == 2

    sh.record_failure("collector.validate_payload", "Found error", {"details": "bad"})
    assert sh.primary_failure_stage == "collector.validate_payload"
    assert sh.primary_failure_reason == "Found error"
    assert sh.last_error_details == {"details": "bad"}


def test_tracker_aggregation():
    tracker = SourceHealthTracker()
    tracker.record_attempt("s1")
    tracker.record_success("s1", "fetch", 1)
    tracker.record_success("s1", "save", 1)

    tracker.record_failure("s2", "collector.fetch", "404")

    tracker.record_filter_rejection("s1", "min_length", 3)

    # Check s1
    s1 = tracker.get_source("s1")
    assert s1.attempted == 1
    assert s1.fetch_ok == 1
    assert s1.saved == 1
    assert s1.skipped_short_content == 3

    # Check s2
    s2 = tracker.get_source("s2")
    assert s2.primary_failure_stage == "collector.fetch"

    tracker.finalize_status()
    assert s1.status == "WORKING"
    assert s2.status == "FAILING"


def test_filter_rejection_counts_cover_each_supported_filter():
    tracker = SourceHealthTracker()
    tracker.record_filter_rejection("s1", "min_length", count=2)
    tracker.record_filter_rejection("s1", "content_too_short", count=3)
    tracker.record_filter_rejection("s1", "title_too_short", count=4)
    tracker.record_filter_rejection("s1", "duplicate", count=5)
    tracker.record_filter_rejection("s1", "top_n", count=6)

    source = tracker.get_source("s1")
    assert source.skipped_short_content == 5
    assert source.skipped_short_title == 4
    assert source.skipped_already_published == 5
    assert source.skipped_top_n_cutoff == 6


def test_export_json(tmp_path: Path):
    tracker = SourceHealthTracker()
    tracker.record_success("s1", "fetch", 1)
    tracker.record_success("s1", "parse", 1)
    tracker.record_success("s1", "save", 1)
    export_path = tmp_path / "report.json"

    with (
        patch.dict(
            "news_collector.diagnostics.ALL_SOURCES",
            {
                "s1": {
                    "name": "Source One",
                    "content_mode": "full_text",
                    "enrichment_strategy": "http",
                },
                "s2": {
                    "name": "Source Two",
                    "content_mode": "summary_only",
                    "enrichment_strategy": "scrapling_stealth",
                },
            },
            clear=True,
        ),
        patch(
            "news_collector.diagnostics.enrichment_metrics.get_all_metrics",
            return_value={"s1": {"headless_seconds_used": 0.0}},
        ),
    ):
        tracker.export_json(str(export_path))

    payload = json.loads(export_path.read_text(encoding="utf-8"))

    sources = payload.get(
        "sources", payload
    )  # current format wraps records in {"sources": ...}
    assert set(sources) == {"s1", "s2"}
    assert SourceHealthRecord.model_validate(sources["s1"]).operational_state == (
        "healthy_full_text"
    )
    assert (
        SourceHealthRecord.model_validate(sources["s2"]).operational_state == "unknown"
    )


def test_print_summary(capsys):
    tracker = SourceHealthTracker()
    tracker.record_success("s1", "save", 1)
    tracker.record_failure("s2", "collector.fetch", "Timeout")

    tracker.print_summary_table()

    captured = capsys.readouterr()
    assert "REPORTE DE SALUD" in captured.out
    assert "s1" in captured.out
    assert "WORKING" in captured.out
    assert "s2" in captured.out
    assert "FAILING" in captured.out


def test_unobserved_source_is_unknown_and_not_suggested_for_blacklisting(
    tmp_path: Path,
):
    tracker = SourceHealthTracker()
    tracker.record_attempt("configured_only")
    export_path = tmp_path / "source-health.json"

    with (
        patch.dict(
            "news_collector.diagnostics.ALL_SOURCES",
            {"configured_only": {"content_mode": "full_text"}},
            clear=True,
        ),
        patch(
            "news_collector.diagnostics.enrichment_metrics.get_all_metrics",
            return_value={},
        ),
    ):
        tracker.export_json(str(export_path))

    payload = json.loads(export_path.read_text(encoding="utf-8"))
    source = SourceHealthRecord.model_validate(payload["sources"]["configured_only"])

    assert tracker.get_source("configured_only").status == "UNKNOWN"
    assert source.operational_state == "unknown"
    assert "suggested_blacklist" not in payload


def test_valid_feed_filtered_to_zero_saved_articles_remains_healthy(
    tmp_path: Path,
):
    tracker = SourceHealthTracker()
    tracker.record_attempt("filtered_feed")
    tracker.record_success("filtered_feed", "fetch")
    tracker.record_success("filtered_feed", "parse", count=2)
    tracker.record_filter_rejection("filtered_feed", "min_length", count=2)
    export_path = tmp_path / "source-health.json"

    with (
        patch.dict(
            "news_collector.diagnostics.ALL_SOURCES",
            {"filtered_feed": {"content_mode": "full_text"}},
            clear=True,
        ),
        patch(
            "news_collector.diagnostics.enrichment_metrics.get_all_metrics",
            return_value={},
        ),
    ):
        tracker.export_json(str(export_path))

    payload = json.loads(export_path.read_text(encoding="utf-8"))
    source = SourceHealthRecord.model_validate(payload["sources"]["filtered_feed"])

    assert source.articles_found == 2
    assert source.articles_saved == 0
    assert source.operational_state == "healthy_full_text"
    assert source.failure_count == 0


def test_pipeline_failure_after_parse_preserves_feed_health_but_is_observable(
    tmp_path: Path,
):
    tracker = SourceHealthTracker()
    tracker.record_attempt("parsed_then_failed")
    tracker.record_success("parsed_then_failed", "fetch")
    tracker.record_success("parsed_then_failed", "parse", count=1)
    tracker.record_failure(
        "parsed_then_failed", "storage.upsert", "database write failed"
    )
    export_path = tmp_path / "source-health.json"

    with (
        patch.dict(
            "news_collector.diagnostics.ALL_SOURCES",
            {"parsed_then_failed": {"content_mode": "full_text"}},
            clear=True,
        ),
        patch(
            "news_collector.diagnostics.enrichment_metrics.get_all_metrics",
            return_value={},
        ),
    ):
        tracker.export_json(str(export_path))

    payload = json.loads(export_path.read_text(encoding="utf-8"))
    source = SourceHealthRecord.model_validate(payload["sources"]["parsed_then_failed"])

    assert source.feed_ok is True
    assert source.pipeline_ok is False
    assert source.failure_count == 1
    assert source.operational_state == "partial_yield_flaky"
    assert tracker.get_source("parsed_then_failed").status == "WORKING"


def test_single_http_failure_is_observable_without_blacklist_suggestion(
    tmp_path: Path,
):
    tracker = SourceHealthTracker()
    tracker.record_attempt("temporarily_unavailable")
    tracker.record_failure(
        "temporarily_unavailable",
        "collector.fetch",
        "HTTP 503",
        {"status_code": 503},
    )
    export_path = tmp_path / "source-health.json"

    with (
        patch.dict(
            "news_collector.diagnostics.ALL_SOURCES",
            {"temporarily_unavailable": {"content_mode": "full_text"}},
            clear=True,
        ),
        patch(
            "news_collector.diagnostics.enrichment_metrics.get_all_metrics",
            return_value={},
        ),
    ):
        tracker.export_json(str(export_path))

    payload = json.loads(export_path.read_text(encoding="utf-8"))
    source = SourceHealthRecord.model_validate(
        payload["sources"]["temporarily_unavailable"]
    )

    assert source.last_error_message == "HTTP 503"
    assert source.failure_count == 1
    assert source.operational_state == "failing_suppressed_candidate"
    assert "suggested_blacklist" not in payload


def test_html_fetch_without_extraction_candidates_is_unknown(tmp_path: Path):
    tracker = SourceHealthTracker()
    tracker.record_attempt("html_without_candidates")
    tracker.record_success("html_without_candidates", "fetch")
    export_path = tmp_path / "source-health.json"

    with (
        patch.dict(
            "news_collector.diagnostics.ALL_SOURCES",
            {"html_without_candidates": {"content_mode": "full_text"}},
            clear=True,
        ),
        patch(
            "news_collector.diagnostics.enrichment_metrics.get_all_metrics",
            return_value={},
        ),
    ):
        tracker.export_json(str(export_path))

    payload = json.loads(export_path.read_text(encoding="utf-8"))
    source = SourceHealthRecord.model_validate(
        payload["sources"]["html_without_candidates"]
    )

    assert source.feed_ok is False
    assert source.operational_state == "unknown"
