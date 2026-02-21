import tempfile
from datetime import datetime
from pathlib import Path

from news_collector.system.activity_monitor import (
    ActivityEvent,
    ActivityMonitor,
    EventAggregator,
    LogParser,
)


def test_parse_valid_line():
    line = "2025-01-28 15:30:00 | INFO     | news_collector.main:100 | Cycle started"
    evt = LogParser.parse_line(line)

    assert evt is not None
    assert evt.timestamp_str == "2025-01-28 15:30:00"
    assert evt.level == "INFO"
    assert evt.category == "Lifecycle"
    assert evt.message == "Cycle started"


def test_parse_fetching_category():
    line = (
        "2025-01-28 15:30:01 | INFO     | news_collector.rss:50 | Fetching RSS from BBC"
    )
    evt = LogParser.parse_line(line)

    assert evt is not None
    assert evt.category == "Collection"


def test_parse_invalid_line():
    line = "Traceback (most recent call last):"
    evt = LogParser.parse_line(line)
    assert evt is None


def test_parse_empty_line():
    assert LogParser.parse_line("   ") is None


def test_log_parser_categories():
    assert LogParser._infer_category("Starting the cycle", "src") == "Lifecycle"
    assert LogParser._infer_category("Fetching RSS feed", "src") == "Collection"
    assert LogParser._infer_category("Scoring article", "src") == "Scoring"
    assert LogParser._infer_category("Publishing to repo", "src") == "Publishing"
    assert LogParser._infer_category("Saving to db", "src") == "Storage"
    assert LogParser._infer_category("Failed to connect", "src") == "System Error"
    assert LogParser._infer_category("System initialized", "src") == "System"


def test_parse_invalid_date():
    line = "invalid-date 15:30:00 | INFO     | news_collector.main:100 | Cycle started"
    # Matches regex but fails datetime parsing, returns None for ts_dt
    line_with_bad_date = "9999-99-99 99:99:99 | INFO | src:1 | Hello"
    # Wait, the regex expects \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}
    evt = LogParser.parse_line(line_with_bad_date)
    assert evt is not None
    assert evt.timestamp_dt is None


def test_aggregation():
    events = [
        LogParser.parse_line("2025-01-28 15:30:00 | INFO | src:1 | Fetching A"),
        LogParser.parse_line("2025-01-28 15:30:01 | INFO | src:1 | Fetching B"),
        LogParser.parse_line("2025-01-28 15:30:02 | INFO | src:1 | Fetching C"),
        LogParser.parse_line("2025-01-28 15:30:05 | INFO | src:1 | Something else"),
    ]

    events_clean = [e for e in events if e]
    agged = EventAggregator.aggregate(events_clean)
    assert len(agged) == 2
    assert "similar events" in agged[0].message
    assert agged[1].message == "Something else"


def test_event_aggregator_empty():
    assert EventAggregator.aggregate([]) == []


def test_activity_monitor_no_file():
    with tempfile.TemporaryDirectory() as td:
        monitor = ActivityMonitor(log_path=Path(td) / "non_existent.log")
        assert monitor.get_recent_activity() == []


def test_activity_monitor_with_file():
    log_content = """2023-10-27 10:00:00 | INFO     | src:1 | Starting cycle
2023-10-27 10:01:00 | INFO     | src:2 | Fetching feed A
2023-10-27 10:02:00 | INFO     | src:2 | Fetching feed B
2023-10-27 10:03:00 | ERROR    | src:3 | Failed connection
"""
    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / "test.log"
        log_path.write_text(log_content)

        monitor = ActivityMonitor(log_path=log_path)
        events = monitor.get_recent_activity()

        assert len(events) == 3
        assert events[0].category == "Lifecycle"
        assert events[1].category == "Collection"
        assert "and 1 similar event" in events[1].message
        assert events[2].category == "System Error"


def test_activity_monitor_default_path():
    monitor = ActivityMonitor()
    assert isinstance(monitor.log_path, Path)


def test_activity_monitor_exception(monkeypatch):
    def mock_open(*args, **kwargs):
        raise ValueError("Simulated error")

    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / "test.log"
        log_path.touch()
        monitor = ActivityMonitor(log_path=log_path)
        monkeypatch.setattr("builtins.open", mock_open)
        # Should catch exception and return []
        assert monitor.get_recent_activity() == []
