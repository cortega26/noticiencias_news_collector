import pytest
from datetime import datetime
from news_collector.system.activity_monitor import LogParser, EventAggregator, ActivityEvent

def test_parse_valid_line():
    line = "2025-01-28 15:30:00 | INFO     | news_collector.main:100 | Cycle started"
    evt = LogParser.parse_line(line)
    
    assert evt is not None
    assert evt.timestamp_str == "2025-01-28 15:30:00"
    assert evt.level == "INFO"
    assert evt.category == "Lifecycle"
    assert evt.message == "Cycle started"

def test_parse_fetching_category():
    line = "2025-01-28 15:30:01 | INFO     | news_collector.rss:50 | Fetching RSS from BBC"
    evt = LogParser.parse_line(line)
    
    assert evt is not None
    assert evt.category == "Collection"

def test_parse_invalid_line():
    line = "Traceback (most recent call last):"
    evt = LogParser.parse_line(line)
    assert evt is None

def test_aggregation():
    events = [
        LogParser.parse_line("2025-01-28 15:30:00 | INFO | src:1 | Fetching A"),
        LogParser.parse_line("2025-01-28 15:30:01 | INFO | src:1 | Fetching B"),
        LogParser.parse_line("2025-01-28 15:30:02 | INFO | src:1 | Fetching C"),
        LogParser.parse_line("2025-01-28 15:30:05 | INFO | src:1 | Something else"),
    ]
    # Filter Nones just in case my mock lines failed regex (they fit the regex roughly if spacing allows)
    # The regex expects strict spacing: ` | `
    # Let's make mock objects manually to avoid regex fragility in this specific test
    
    events = [
        ActivityEvent("t1", None, "INFO", "Collection", "Fetching A", ""),
        ActivityEvent("t2", None, "INFO", "Collection", "Fetching B", ""),
        ActivityEvent("t3", None, "INFO", "Collection", "Fetching C", ""),
        ActivityEvent("t4", None, "INFO", "Lifecycle", "Something else", ""),
    ]
    
    agged = EventAggregator.aggregate(events)
    assert len(agged) == 2
    assert "similar events" in agged[0].message
    assert agged[1].message == "Something else"
