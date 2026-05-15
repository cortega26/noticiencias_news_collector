import json
from pathlib import Path
from unittest.mock import patch

from news_collector.diagnostics import SourceHealth, SourceHealthTracker
from news_collector.contracts.source_health import SourceHealthRecord


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
    )  # new format wraps in {"sources": ..., "suggested_blacklist": ...}
    assert set(sources) == {"s1", "s2"}
    assert SourceHealthRecord.model_validate(sources["s1"]).operational_state == (
        "healthy_full_text"
    )
    assert SourceHealthRecord.model_validate(sources["s2"]).operational_state == (
        "failing_suppressed_candidate"
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
