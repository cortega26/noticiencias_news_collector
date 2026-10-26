import os
from datetime import datetime, timezone

# Set test mode BEFORE importing any news_collector package module:
# get_logger() configures the loguru file sink on first import, and that
# first import happens while this conftest module is being loaded (via
# `from news_collector.storage import database` below) — before any
# pytest_configure hook runs. Without this, pytest would write test noise
# into the production data/logs/collector.log.
os.environ.setdefault("NEWS_COLLECTOR_TEST_MODE", "1")
# Aísla la suite del .env local del repo: sin esto, sus overrides (p. ej. pesos
# de scoring) se mezclan con las configs temporales de los tests. Los
# subprocesos heredan la variable.
os.environ.setdefault(
    "NOTICIENCIAS_DEFAULT_ENV_PATH",
    os.path.join(os.path.dirname(__file__), "_no_such_dir", ".env"),
)

import sqlite3

import pytest

from news_collector.logic.workflows import publication_run_workflow
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


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    """Drain dispatched publication workers before fixture finalizers run.

    Fixture finalizers execute inside this hook, and a test-requested fixture
    such as ``monkeypatch`` finalizes *before* the autouse DB fixture. Joining
    only in the fixture would therefore let a still-starting batch pick up the
    already-restored real pipeline (and then the closed DB). Joining here runs
    while every fixture — including the test's fakes — is still installed.
    """
    publication_run_workflow.join_dispatched_publication_threads()
    yield


@pytest.fixture(autouse=True)
def _restore_runtime_config_state():
    """Restore the global runtime-config state around every test (plan 152).

    ``refresh_runtime_config()`` mutates the process-wide ``RUNTIME`` holder
    and publishes a new ``_CURRENT_SNAPSHOT``.  A test that refreshes with a
    partial config — e.g. ``test_main_manual_url`` drives
    ``run_publication_pipeline`` with a ``SimpleNamespace`` (a non-``Config``
    double, so the resolvers/builders are skipped) while a previous test's
    teardown has already swapped ``RUNTIME`` for a pristine
    ``RuntimeSettings()`` — leaves a snapshot with empty ``database_config``
    (``KeyError: 'type'`` in ``DatabaseManager._setup_database``) and no
    ``min_content_length`` (admission falls back to 1000).  Later tests then
    read it via ``get_runtime_config()`` as if it were their own.  Reproduce
    with ``-p randomly`` seeds ``722672841`` / ``303127521``.

    The process-wide global is production semantics (refreshed once per
    pipeline cycle), so the isolation belongs here, in the harness: save the
    module globals plus every ``RUNTIME`` field (identity references only —
    the resolvers rebind whole attributes and dicts, they never mutate the
    previous dicts in place), then restore them in ``finally``.

    Manual save/restore, not ``monkeypatch``: an autouse fixture that depends
    on ``monkeypatch`` changes the teardown order of every test that patches
    module state itself (see ``_allow_example_com_source_images``).
    """
    import dataclasses

    from news_collector.config import settings as settings_module

    runtime = settings_module.RUNTIME
    saved_runtime_fields = {
        field.name: getattr(runtime, field.name)
        for field in dataclasses.fields(runtime)
    }
    saved_snapshot = settings_module._CURRENT_SNAPSHOT
    saved_config_state = settings_module._CONFIG_STATE
    saved_version = settings_module._CONFIG_VERSION
    try:
        yield
    finally:
        settings_module._CURRENT_SNAPSHOT = saved_snapshot
        settings_module._CONFIG_STATE = saved_config_state
        settings_module._CONFIG_VERSION = saved_version
        # A test may have swapped RUNTIME for a new holder (module reload or
        # an explicit cleanup); restore the original object and its pre-test
        # field values so accessors see a consistent state again.
        settings_module.RUNTIME = runtime
        for name, value in saved_runtime_fields.items():
            setattr(runtime, name, value)


@pytest.fixture(autouse=True)
def _close_global_db_manager():
    yield
    # Last line of defence before the shared manager is closed: a publication
    # worker still finishing would otherwise reach complete()/fail() against
    # a disposed engine (issue #367). The registry is module-level because
    # teardown has no workflow instance. No timeout: a hung worker must fail
    # loudly rather than be hidden by closing the DB underneath it.
    publication_run_workflow.join_dispatched_publication_threads()
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
