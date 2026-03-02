import pytest
import logging
from unittest.mock import MagicMock
from news_collector.logic.parsers.rss_parser import RssParser


def test_rss_parser_logs_corrupt_entry(caplog):
    parser = RssParser()
    feed_mock = MagicMock()

    class CorruptEntry:
        def get(self, key, default=""):
            if key == "link":
                return "https://valid.source/"
            raise ValueError("Corrupt entry!")

    feed_mock.entries = [CorruptEntry()]

    with caplog.at_level(logging.WARNING):
        items = parser.extract_items(feed_mock, {"id": "test_source"})

    assert len(items) == 0
    assert (
        "Failed to extract item from feed 'test_source': Corrupt entry!" in caplog.text
    )
    assert "ValueError: Corrupt entry!" in caplog.text


def test_rss_parser_logs_corrupt_timestamp(caplog):
    parser = RssParser()
    feed_mock = MagicMock()

    class EntryWithBadDate:
        published = "not a date"

        def get(self, key, default=""):
            if key == "link":
                return "https://valid.source/"
            elif key == "title":
                return "Valid title"
            return default

    feed_mock.entries = [EntryWithBadDate()]

    with caplog.at_level(logging.WARNING):
        items = parser.extract_items(feed_mock, {"id": "test_source"})

    assert "Failed to parse timestamp field 'published'" in caplog.text


def test_rss_parser_batch_summary(caplog):
    parser = RssParser()
    feed_mock = MagicMock()

    class FailingEntry:
        def get(self, key, default=""):
            if key == "link":
                return "https://valid.source/"
            raise TypeError("bad type!")

    feed_mock.entries = [FailingEntry()] * 5

    with caplog.at_level(logging.WARNING):
        parser.extract_items(feed_mock, {"id": "src-1"})

    with caplog.at_level(logging.INFO):
        parser.print_batch_summary()

    assert "--- RSS Parser Summary [src-1] ---" in caplog.text
    assert "Failed Items: 5" in caplog.text
