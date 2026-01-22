import pytest
from pathlib import Path
import feedparser
from datetime import datetime, timezone
from news_collector.logic.parsers.rss_parser import RssParser

@pytest.fixture
def rss_sample_path():
    return Path(__file__).parent.parent.parent / "fixtures" / "xml" / "rss_sample.xml"

@pytest.fixture
def rss_content(rss_sample_path):
    with open(rss_sample_path, "r", encoding="utf-8") as f:
        return f.read()

def test_rss_parser_golden_file(rss_content):
    """Test RSS extraction against a golden file."""
    # Placeholder for more specific golden file check if needed
    pass

def test_rss_parser_mapping(rss_content):
    """Verify mapping of RSS fields to Article model."""
    parser = RssParser()
    parsed_feed = parser.parse_feed_content(rss_content)
    
    source_config = {"category": "Science"}
    candidates = parser.extract_items(parsed_feed, source_config)
    
    assert len(candidates) == 2
    
    # Item 1: NASA Discovery
    item1 = candidates[0]
    assert item1["title"] == "NASA Discovery"
    assert item1["url"] == "https://nasa.gov/news/discovery"
    assert item1["category"] == "Science"
    assert "NASA Admin" in item1["authors"] 
    assert item1["published_date"].year == 2026
    
    # Item 2: Quantum Leap
    item2 = candidates[1]
    assert item2["title"] == "Quantum Leap"
    assert item2["original_url"] == "https://science.org/quantum"
    assert "Big breakthrough" in item2["summary"] 
    assert item2["source_metadata"]["entry_id"] == "unique-id-123" 
