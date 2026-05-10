"""Tests for SessionReporter — extracted from reporting.generate_session_report."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from news_collector.system.reporter import SessionReporter


@pytest.fixture
def system():
    sys = MagicMock()
    sys.system_id = "sys-001"
    sys.start_time = datetime.now(timezone.utc)
    sys.logger = MagicMock()
    sys.logger.create_module_logger.return_value = sys.logger
    return sys


@pytest.fixture
def reporter(system):
    return SessionReporter(system)


_COLLECTION_RESULTS = {
    "collection_summary": {
        "sources_processed": 5,
        "articles_found": 100,
        "articles_saved": 80,
        "success_rate_percent": 95.0,
    },
    "source_details": {"src1": {"articles_saved": 50}, "src2": {"articles_saved": 30}},
}

_SCORING_RESULTS = {
    "statistics": {
        "articles_scored": 80,
        "articles_included": 40,
        "articles_excluded": 40,
        "average_score": 0.65,
    }
}

_SELECTION_RESULTS = {
    "selected_count": 15,
    "articles": [{"id": i, "score": 0.8} for i in range(15)],
}


class TestReportStructure:
    def test_full_report_contains_expected_sections(self, reporter):
        report = reporter.generate_report(
            collection_results=_COLLECTION_RESULTS,
            scoring_results=_SCORING_RESULTS,
            selection_results=_SELECTION_RESULTS,
            session_id="sess-001",
        )

        assert "schema_version" in report
        assert "session_info" in report
        assert "collection_results" in report
        assert "scoring_results" in report
        assert "selection_results" in report
        assert "performance_metrics" in report
        assert "summary" in report

    def test_session_info(self, reporter):
        report = reporter.generate_report(
            collection_results=_COLLECTION_RESULTS,
            scoring_results=_SCORING_RESULTS,
            selection_results=_SELECTION_RESULTS,
            session_id="sess-001",
        )

        info = report["session_info"]
        assert info["session_id"] == "sess-001"
        assert info["system_id"] == "sys-001"
        assert "start_time" in info
        assert "end_time" in info
        assert "duration_seconds" in info

    def test_summary_aggregates(self, reporter):
        report = reporter.generate_report(
            collection_results=_COLLECTION_RESULTS,
            scoring_results=_SCORING_RESULTS,
            selection_results=_SELECTION_RESULTS,
            session_id="sess-001",
        )

        summary = report["summary"]
        assert summary["sources_processed"] == 5
        assert summary["articles_found"] == 100
        assert summary["articles_saved"] == 80
        assert summary["articles_scored"] == 80
        assert summary["final_selection_count"] == 15

    def test_performance_metrics(self, reporter):
        report = reporter.generate_report(
            collection_results=_COLLECTION_RESULTS,
            scoring_results=_SCORING_RESULTS,
            selection_results=_SELECTION_RESULTS,
            session_id="sess-001",
        )

        metrics = report["performance_metrics"]
        assert metrics["articles_per_second"] > 0
        assert metrics["sources_per_minute"] > 0
        assert metrics["success_rate_percent"] == 95.0


class TestEdgeCases:
    def test_empty_collection_results(self, reporter):
        report = reporter.generate_report(
            collection_results={},
            scoring_results=_SCORING_RESULTS,
            selection_results=_SELECTION_RESULTS,
            session_id="sess-002",
        )

        # Should not crash, empty defaults used
        assert report["summary"]["sources_processed"] == 0

    def test_empty_scoring_results(self, reporter):
        report = reporter.generate_report(
            collection_results=_COLLECTION_RESULTS,
            scoring_results={},
            selection_results=_SELECTION_RESULTS,
            session_id="sess-003",
        )

        assert report["summary"]["articles_scored"] == 0


class TestHealthExport:
    @patch("news_collector.system.reporter.Path")
    def test_health_export_called(self, mock_path, reporter):
        mock_path.return_value.parent.mkdir.return_value = None

        reporter.generate_report(
            collection_results=_COLLECTION_RESULTS,
            scoring_results=_SCORING_RESULTS,
            selection_results=_SELECTION_RESULTS,
            session_id="sess-004",
        )

        # Should not crash; health export is best-effort
        pass

    @patch("news_collector.system.reporter.serialize_source_health_report")
    def test_health_export_failure_is_nonfatal(
        self, mock_serialize, reporter
    ):
        """If health export fails, the report is still returned."""
        mock_serialize.side_effect = OSError("Permission denied")

        report = reporter.generate_report(
            collection_results=_COLLECTION_RESULTS,
            scoring_results=_SCORING_RESULTS,
            selection_results=_SELECTION_RESULTS,
            session_id="sess-005",
        )

        assert report is not None
        assert report["schema_version"] == 2  # still a valid report
