from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from news_collector.contracts.source_health import SourceHealthRecord
from news_collector.system.reporter import SessionReporter


def test_generate_session_report_exports_stable_source_health_shape(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    system = SimpleNamespace(
        start_time=datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc),
        system_id="test-system",
        logger=MagicMock(),
    )
    system.logger.create_module_logger.return_value = MagicMock()
    reporter = SessionReporter(system)

    collection_results = {
        "collection_summary": {
            "sources_processed": 1,
            "articles_found": 2,
            "articles_saved": 1,
            "success_rate_percent": 50,
        },
        "source_details": {
            "s1": {
                "feed_ok": True,
                "pipeline_ok": True,
                "content_ok": True,
                "articles_found": 2,
                "articles_saved": 1,
                "content_mode": "summary_only",
                "enrichment_strategy": "scrapling_stealth",
                "latency": 0.8,
            }
        },
    }

    with (
        patch.dict(
            "news_collector.config.sources.ALL_SOURCES",
            {
                "s1": {
                    "name": "Source One",
                    "content_mode": "summary_only",
                    "enrichment_strategy": "scrapling_stealth",
                },
                "s2": {
                    "name": "Source Two",
                    "content_mode": "full_text",
                    "enrichment_strategy": "http",
                },
            },
            clear=True,
        ),
        patch(
            "news_collector.system.reporter.enrichment_metrics.get_all_metrics",
            return_value={
                "s1": {
                    "headless_seconds_used": 3.0,
                    "scrapling_stealth_attempts": 2,
                    "scrapling_stealth_success": 1,
                }
            },
        ),
    ):
        report = reporter.generate_report(
            collection_results=collection_results,
            scoring_results={"statistics": {"articles_scored": 1}},
            selection_results={"selected_count": 1},
            session_id="session-1",
        )

    assert report["summary"]["articles_saved"] == 1

    export_payload = (tmp_path / "data" / "exports" / "source_health.json").read_text(
        encoding="utf-8"
    )
    source_health = __import__("json").loads(export_payload)

    assert set(source_health) == {"s1", "s2"}
    validated_s1 = SourceHealthRecord.model_validate(source_health["s1"])
    assert validated_s1.headless_seconds_used == 3.0
    assert validated_s1.scrapling_stealth_success_rate == 0.5
    assert (
        SourceHealthRecord.model_validate(source_health["s2"]).operational_state
        == "failing_suppressed_candidate"
    )
