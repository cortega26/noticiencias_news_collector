import os
from datetime import datetime, timezone

# Set test mode BEFORE importing any news_collector package module:
# get_logger() configures the loguru file sink on first import, and that
# first import happens while this conftest module is being loaded (via
# `from news_collector.storage import database` below) — before any
# pytest_configure hook runs. Without this, pytest would write test noise
# into the production data/logs/collector.log.
os.environ.setdefault("NEWS_COLLECTOR_TEST_MODE", "1")

import sqlite3

import pytest

from news_collector.storage import database as database_module

# Frozen instant for fixture payload timestamps, so shared fixtures cannot
# drift into time-bomb behavior as the wall clock moves.
_FIXED_PAYLOAD_INSTANT = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _allow_example_com_source_images():
    """Publication tests mock the downloader and use https://example.com images.

    The shipped allowlist is empty (source images are not reused without a
    licence); the policy itself is covered in
    tests/decompose_refinery/test_image_handler.py with explicit handlers.

    Restores the attribute by hand instead of requesting ``monkeypatch``: an
    autouse fixture that depends on ``monkeypatch`` changes the teardown order
    of every test that patches module state itself.
    """
    from news_collector.logic.workflows import image_handler

    original = image_handler.REMOTE_IMAGE_ALLOWLIST
    image_handler.REMOTE_IMAGE_ALLOWLIST = frozenset({"example.com"})
    try:
        yield
    finally:
        image_handler.REMOTE_IMAGE_ALLOWLIST = original


@pytest.fixture(autouse=True)
def _close_global_db_manager():
    yield
    manager = getattr(database_module, "_db_manager", None)
    if manager is not None:
        manager.close()
        database_module._db_manager = None


@pytest.fixture
def mock_article_payload():
    """Returns a valid dictionary payload for a CollectorArticleModel."""
    return {
        "url": "https://example.com/test-article",
        "original_url": "https://example.com/test-article",
        "title": "A Valid Title for Testing Purposes",
        "summary": "This is a sufficiently long summary that meets the minimum length requirements for testing validation logic.",
        "content": (
            "This is the main content of the article. It has enough words to pass the validation "
            "checks. We need to ensure that the content is sufficiently long so that the heuristic "
            "rules for quality do not trigger a validation error. This should be more than enough characters now. "
            * 30
        ),
        "source_id": "test_source",
        "source_name": "Test Source",
        "category": "science",
        "published_date": _FIXED_PAYLOAD_INSTANT,
        "published_tz_offset_minutes": 0,
        "published_tz_name": "UTC",
        "authors": ["Test Author"],
        "language": "en",
        "word_count": 100,
        "reading_time_minutes": 5,
        "article_metadata": {
            "credibility_score": 0.9,
            "processing_timestamp": _FIXED_PAYLOAD_INSTANT.isoformat(),
            "original_url": "https://example.com/test-article",
        },
    }


def pytest_sessionfinish(session, exitstatus):
    """Clean up global sqlite connections after all tests to prevent ResourceWarnings."""
    import logging

    try:
        from news_collector.observability.enrichment_metrics_store import (
            enrichment_metrics,
            production_metrics_view,
        )

        enrichment_metrics.close()
        production_metrics_view.close()
    except (ImportError, AttributeError, sqlite3.OperationalError) as e:
        logging.warning("Skipped cleanup of metrics DB: %s", e)
