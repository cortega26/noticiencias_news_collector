from unittest.mock import mock_open, patch

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


def test_export_json():
    tracker = SourceHealthTracker()
    tracker.record_success("s1", "save", 1)

    m_open = mock_open()
    with patch("builtins.open", m_open), patch("pathlib.Path.mkdir"):
        tracker.export_json("report.json")

    # assert call arguments
    # open is called with a Path object, checking strict quality might fail so use ANY or check str
    from unittest.mock import ANY

    m_open.assert_called_with(ANY, "w", encoding="utf-8")
    handle = m_open()
    # verify write happened - tough with json.dump to mock file, but basic call ensures path reached
    assert handle.write.called


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
