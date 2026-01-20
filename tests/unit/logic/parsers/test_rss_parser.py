import unittest
from news_collector.logic.parsers.rss_parser import RssParser
from unittest.mock import MagicMock

class TestRssParser(unittest.TestCase):
    def setUp(self):
        self.parser = RssParser()

    def test_parse_simple_entry(self):
        # Mock a feedparser entry
        entry = MagicMock()
        entry.get.side_effect = lambda k, d=None: {"title": "Test Title", "link": "http://example.com"}.get(k, d)
        entry.title = "Test Title"
        entry.link = "http://example.com"
        entry.summary = "Test Summary"
        entry.published_parsed = (2023, 1, 1, 12, 0, 0, 0, 0, 0) # struct_time
        
        parsed_feed = MagicMock()
        parsed_feed.feed = MagicMock()
        parsed_feed.entries = [entry]
        
        candidates = self.parser.extract_items(parsed_feed, {"category": "test"})
        
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["title"], "Test Title")
        self.assertEqual(candidates[0]["url"], "https://example.com/") # Canonicalized (Http -> Https)

    def test_extract_doi(self):
        entry = MagicMock()
        entry.get.side_effect = lambda k, d=None: "".get(k, d)
        entry.id = "doi:10.1038/s41586-020-2649-2"
        entry.links = []
        
        # We need to expose _extract_doi or test via extract_items metadata
        parsed_feed = MagicMock() 
        parsed_feed.entries = [entry]
        # But extract_items requires entry to have link and title
        entry.get.side_effect = lambda k, d=None: {"link": "http://x.com", "title": "DOI Test"}.get(k, d)
        
        candidates = self.parser.extract_items(parsed_feed, {})
        metadata = candidates[0].get("source_metadata", {})
        self.assertEqual(metadata.get("doi"), "10.1038/s41586-020-2649-2")

    def test_bozo_detection(self):
        feed = MagicMock()
        feed.bozo = 1
        feed.bozo_exception = MagicMock()
        feed.bozo_exception.__class__.__name__ = "InvalidDocument" # Acceptable
        
        self.assertTrue(self.parser.is_acceptable_bozo(feed))
        
        feed.bozo_exception.__class__.__name__ = "SAXParseException" # Unacceptable (maybe)
        self.assertFalse(self.parser.is_acceptable_bozo(feed))

if __name__ == "__main__":
    unittest.main()
