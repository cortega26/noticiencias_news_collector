"""Tests for SourceRepository — covering circuit breaker, feed metadata, and stats paths."""

from datetime import datetime, timedelta, timezone

import pytest

from news_collector.storage.database import DatabaseManager
from news_collector.storage.source_repository import SourceRepository

_BASE_SOURCE = {
    "name": "Test Source",
    "url": "https://example.com/feed.xml",
    "credibility_score": 0.8,
    "category": "science",
}


@pytest.fixture
def db_manager(tmp_path):
    manager = DatabaseManager(
        database_config={"type": "sqlite", "path": tmp_path / "test.db"}
    )
    yield manager
    manager.close()


@pytest.fixture
def repo(db_manager):
    return SourceRepository(db_manager)


@pytest.fixture
def seeded_repo(repo):
    repo.initialize_sources({"src1": _BASE_SOURCE})
    return repo


# ---------------------------------------------------------------------------
# get_source_circuit_state
# ---------------------------------------------------------------------------


def test_get_circuit_state_missing_source(repo):
    assert repo.get_source_circuit_state("nonexistent") is None


def test_get_circuit_state_existing_source(seeded_repo):
    state = seeded_repo.get_source_circuit_state("src1")
    assert state is not None
    assert state["status"] == "ACTIVE"
    assert state["consecutive_failures"] == 0


# ---------------------------------------------------------------------------
# update_source_circuit_state — failure paths (lines 75-108)
# ---------------------------------------------------------------------------


def test_update_circuit_state_success_noop_when_already_active(seeded_repo):
    seeded_repo.update_source_circuit_state("src1", success=True)
    state = seeded_repo.get_source_circuit_state("src1")
    assert state["status"] == "ACTIVE"
    assert state["consecutive_failures"] == 0


def test_update_circuit_state_success_resets_failure_count(seeded_repo):
    seeded_repo.update_source_circuit_state("src1", success=False)
    seeded_repo.update_source_circuit_state("src1", success=True)
    state = seeded_repo.get_source_circuit_state("src1")
    assert state["consecutive_failures"] == 0
    assert state["status"] == "ACTIVE"


def test_update_circuit_state_failure_increments_count(seeded_repo):
    seeded_repo.update_source_circuit_state(
        "src1", success=False, error_message="timeout"
    )
    state = seeded_repo.get_source_circuit_state("src1")
    assert state["consecutive_failures"] == 1
    assert state["status"] == "ACTIVE"


def test_update_circuit_state_trips_to_cooldown_after_max_failures(seeded_repo):
    from news_collector.config.settings import COLLECTION_CONFIG

    max_failures = COLLECTION_CONFIG.get("circuit_breaker_max_failures", 3)
    for _ in range(max_failures):
        seeded_repo.update_source_circuit_state("src1", success=False)
    state = seeded_repo.get_source_circuit_state("src1")
    assert state["status"] == "COOLDOWN"
    assert state["next_retry_at"] is not None


def test_update_circuit_state_force_cooldown(seeded_repo):
    until = datetime.now(timezone.utc) + timedelta(hours=1)
    seeded_repo.update_source_circuit_state(
        "src1", success=False, error_message="429", force_cooldown_until=until
    )
    state = seeded_repo.get_source_circuit_state("src1")
    assert state["status"] == "COOLDOWN"
    assert state["next_retry_at"] is not None


def test_update_circuit_state_missing_source_is_noop(repo):
    repo.update_source_circuit_state("ghost", success=False)  # must not raise


# ---------------------------------------------------------------------------
# initialize_sources — blacklist update paths (lines 134, 136, 138, 140, 142-143)
# ---------------------------------------------------------------------------


def test_initialize_sources_creates_new_source(repo):
    repo.initialize_sources({"newsrc": _BASE_SOURCE})
    state = repo.get_source_circuit_state("newsrc")
    assert state is not None


def test_initialize_sources_updates_existing_source(seeded_repo):
    updated = dict(_BASE_SOURCE, name="Updated Name")
    seeded_repo.initialize_sources({"src1": updated})
    state = seeded_repo.get_source_circuit_state("src1")
    assert state is not None


def test_initialize_sources_sets_blacklist_fields(seeded_repo):
    config = dict(
        _BASE_SOURCE,
        blacklisted=True,
        blacklist_reason="spam",
        blacklisted_date="2026-01-15",
    )
    seeded_repo.initialize_sources({"src1": config})
    state = seeded_repo.get_source_circuit_state("src1")
    assert state is not None


def test_initialize_sources_handles_invalid_blacklisted_date(seeded_repo):
    config = dict(_BASE_SOURCE, blacklisted_date="not-a-date")
    seeded_repo.initialize_sources({"src1": config})  # must not raise


# ---------------------------------------------------------------------------
# update_source_feed_metadata — content_hash + conditional branches (lines 196-209)
# ---------------------------------------------------------------------------


def test_update_feed_metadata_noop_when_all_none(seeded_repo):
    seeded_repo.update_source_feed_metadata("src1")  # must not raise


def test_update_feed_metadata_etag(seeded_repo):
    seeded_repo.update_source_feed_metadata("src1", etag="abc123")
    meta = seeded_repo.get_source_feed_metadata("src1")
    assert meta["etag"] == "abc123"


def test_update_feed_metadata_last_modified(seeded_repo):
    seeded_repo.update_source_feed_metadata(
        "src1", last_modified="Wed, 01 Jan 2026 00:00:00 GMT"
    )
    meta = seeded_repo.get_source_feed_metadata("src1")
    assert meta["last_modified"] == "Wed, 01 Jan 2026 00:00:00 GMT"


def test_update_feed_metadata_content_hash(seeded_repo):
    seeded_repo.update_source_feed_metadata("src1", content_hash="sha256:deadbeef")
    meta = seeded_repo.get_source_feed_metadata("src1")
    assert meta is not None


def test_update_feed_metadata_missing_source_is_noop(repo):
    repo.update_source_feed_metadata("ghost", etag="x")  # must not raise


# ---------------------------------------------------------------------------
# update_source_stats — articles found + failure + success_rate (lines 224-236)
# ---------------------------------------------------------------------------


def test_update_source_stats_success_with_articles(seeded_repo):
    seeded_repo.update_source_stats("src1", {"success": True, "articles_found": 5})
    state = seeded_repo.get_source_circuit_state("src1")
    assert state["consecutive_failures"] == 0


def test_update_source_stats_success_no_articles(seeded_repo):
    seeded_repo.update_source_stats("src1", {"success": True, "articles_found": 0})
    state = seeded_repo.get_source_circuit_state("src1")
    assert state["consecutive_failures"] == 0


def test_update_source_stats_failure_increments_count(seeded_repo):
    seeded_repo.update_source_stats(
        "src1", {"success": False, "error_message": "timeout"}
    )
    state = seeded_repo.get_source_circuit_state("src1")
    assert state["consecutive_failures"] == 1


def test_update_source_stats_success_rate_computed(seeded_repo):
    seeded_repo.update_source_stats("src1", {"success": True, "articles_found": 10})
    seeded_repo.update_source_stats("src1", {"success": False})
    state = seeded_repo.get_source_circuit_state("src1")
    assert state["consecutive_failures"] == 1


def test_update_source_stats_missing_source_is_noop(repo):
    repo.update_source_stats(
        "ghost", {"success": True, "articles_found": 1}
    )  # must not raise


def test_initialize_sources_sets_etag_and_last_modified_on_existing(seeded_repo):
    config = dict(
        _BASE_SOURCE, etag="etag-value", last_modified="Mon, 01 Jan 2026 00:00:00 GMT"
    )
    seeded_repo.initialize_sources({"src1": config})
    meta = seeded_repo.get_source_feed_metadata("src1")
    assert meta["etag"] == "etag-value"
    assert meta["last_modified"] == "Mon, 01 Jan 2026 00:00:00 GMT"


def test_get_feed_metadata_missing_source_returns_empty(repo):
    result = repo.get_source_feed_metadata("nonexistent")
    assert result == {}
