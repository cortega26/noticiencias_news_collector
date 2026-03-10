import pytest
from unittest.mock import MagicMock
from loguru import logger
from news_collector.logic.parsers.rss_parser import RssParser


def test_rss_parser_logs_corrupt_entry():
    parser = RssParser()
    feed_mock = MagicMock()

    class CorruptEntry:
        def get(self, key, default=""):
            if key == "link":
                return "https://valid.source/"
            raise ValueError("Corrupt entry!")

    feed_mock.entries = [CorruptEntry()]

    messages = []
    handler_id = logger.add(lambda m: messages.append(m))
    try:
        items = parser.extract_items(feed_mock, {"id": "test_source"})
    finally:
        logger.remove(handler_id)

    assert len(items) == 0
    combined = "".join(messages)
    assert (
        "Failed to extract item from feed 'test_source': Corrupt entry!" in combined
    )


def test_rss_parser_logs_corrupt_timestamp():
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

    messages = []
    handler_id = logger.add(lambda m: messages.append(m))
    try:
        items = parser.extract_items(feed_mock, {"id": "test_source"})
    finally:
        logger.remove(handler_id)

    combined = "".join(messages)
    assert "Failed to parse timestamp field 'published'" in combined


def test_rss_parser_batch_summary():
    parser = RssParser()
    feed_mock = MagicMock()

    class FailingEntry:
        def get(self, key, default=""):
            if key == "link":
                return "https://valid.source/"
            raise TypeError("bad type!")

    feed_mock.entries = [FailingEntry()] * 5

    messages = []
    handler_id = logger.add(lambda m: messages.append(m))
    try:
        parser.extract_items(feed_mock, {"id": "src-1"})
        parser.print_batch_summary()
    finally:
        logger.remove(handler_id)

    combined = "".join(messages)
    assert "--- RSS Parser Summary [src-1] ---" in combined
    assert "Failed Items: 5" in combined
