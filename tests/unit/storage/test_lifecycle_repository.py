"""Unit tests for LifecycleRepository (Plan 060 / Phase 3b).

Uses a real SQLite database through DatabaseManager, matching the
`tmp_path`-fixture convention already used by
tests/test_database_migrations.py and tests/unit/storage/test_article_repository_coverage.py.
"""

from datetime import datetime, timezone

import pytest

from news_collector.storage.database import DatabaseManager
from news_collector.storage.lifecycle_repository import (
    AUDIT_LEGACY_STATE_TO_OUTCOME,
    map_legacy_audit_outcome,
)
from news_collector.storage.models import Base


@pytest.fixture
def db_manager(tmp_path):
    db_file = tmp_path / "lifecycle_repo.db"
    manager = DatabaseManager({"type": "sqlite", "path": db_file})
    Base.metadata.create_all(manager.engine)
    manager.initialize_sources(
        {
            "src1": {
                "url": "http://a.com",
                "name": "Source A",
                "credibility_score": 1.0,
                "category": "general",
            }
        }
    )
    yield manager
    manager.close()


def _article_payload(url, seed):
    return {
        "title": f"Lifecycle test title {seed}",
        "url": url,
        "source_id": "src1",
        "source_name": "Source A",
        "category": "tech",
        "published_date": datetime.now(timezone.utc),
        "content": f"Content {seed} " * 50,
        "summary": f"Summary {seed} " * 20,
        "word_count": 100,
        "reading_time_minutes": 1,
        "authors": ["Test Author"],
        "language": "en",
    }


def _make_article(db_manager, seed):
    saved = db_manager.articles.save_article(
        _article_payload(f"https://x.com/{seed}", seed)
    )
    return int(saved.id)


# ---------------------------------------------------------------------------
# publication_attempts — append-only insert
# ---------------------------------------------------------------------------


def test_record_publication_attempt_defaults_attempt_number_via_count(db_manager):
    article_id = _make_article(db_manager, "pub1")
    started = datetime.now(timezone.utc)

    first = db_manager.lifecycle.record_publication_attempt(
        article_id,
        refinery_id="ref-1",
        state="PR_CREATED",
        started_at=started,
        pr_url="https://example.com/pr/1",
    )
    assert first.attempt_number == 1
    assert first.article_id == article_id
    assert first.state == "PR_CREATED"
    assert first.pr_url == "https://example.com/pr/1"

    second = db_manager.lifecycle.record_publication_attempt(
        article_id,
        refinery_id="ref-2",
        state="PR_CREATED",
        started_at=started,
    )
    assert second.attempt_number == 2


def test_record_publication_attempt_explicit_attempt_number_bypasses_count(db_manager):
    article_id = _make_article(db_manager, "pub2")
    started = datetime.now(timezone.utc)

    # Backfill's own use case: always attempt 1, regardless of how many
    # rows already exist for this article.
    db_manager.lifecycle.record_publication_attempt(
        article_id, refinery_id="a", state="PR_CREATED", started_at=started
    )
    forced = db_manager.lifecycle.record_publication_attempt(
        article_id,
        refinery_id="b",
        state="PR_CREATED",
        started_at=started,
        attempt_number=1,
    )
    assert forced.attempt_number == 1


# ---------------------------------------------------------------------------
# transition_publication_attempt — CAS
# ---------------------------------------------------------------------------


def test_transition_publication_attempt_cas_success(db_manager):
    article_id = _make_article(db_manager, "cas1")
    started = datetime.now(timezone.utc)
    attempt = db_manager.lifecycle.record_publication_attempt(
        article_id, refinery_id="ref-cas-1", state="PR_CREATED", started_at=started
    )

    ok = db_manager.lifecycle.transition_publication_attempt(
        attempt.id,
        from_state="PR_CREATED",
        to_state="COMPLETED",
        finished_at=datetime.now(timezone.utc),
    )
    assert ok is True

    [reloaded] = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    assert reloaded.state == "COMPLETED"
    assert reloaded.finished_at is not None


def test_transition_publication_attempt_cas_miss_already_transitioned(db_manager):
    article_id = _make_article(db_manager, "cas2")
    started = datetime.now(timezone.utc)
    attempt = db_manager.lifecycle.record_publication_attempt(
        article_id, refinery_id="ref-cas-2", state="PR_CREATED", started_at=started
    )

    first = db_manager.lifecycle.transition_publication_attempt(
        attempt.id, from_state="PR_CREATED", to_state="REJECTED"
    )
    assert first is True

    # Concurrent/replayed transition attempt against the now-stale expected
    # state: must return False, not raise.
    second = db_manager.lifecycle.transition_publication_attempt(
        attempt.id, from_state="PR_CREATED", to_state="COMPLETED"
    )
    assert second is False

    [reloaded] = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    assert reloaded.state == "REJECTED"


def test_transition_publication_attempt_cas_miss_nonexistent_row(db_manager):
    ok = db_manager.lifecycle.transition_publication_attempt(
        999999, from_state="PR_CREATED", to_state="COMPLETED"
    )
    assert ok is False


def test_publication_attempt_exists(db_manager):
    article_id = _make_article(db_manager, "exists1")
    started = datetime.now(timezone.utc)
    assert db_manager.lifecycle.publication_attempt_exists(article_id, "ref-x") is False
    db_manager.lifecycle.record_publication_attempt(
        article_id, refinery_id="ref-x", state="PR_CREATED", started_at=started
    )
    assert db_manager.lifecycle.publication_attempt_exists(article_id, "ref-x") is True


# ---------------------------------------------------------------------------
# editorial_decisions — append-only insert
# ---------------------------------------------------------------------------


def test_record_editorial_decision_append_only(db_manager):
    article_id = _make_article(db_manager, "ed1")
    decided = datetime.now(timezone.utc)

    decision = db_manager.lifecycle.record_editorial_decision(
        article_id=article_id,
        decision_type="auditor",
        outcome="pass",
        reason="looks fine",
        decided_at=decided,
        details={"attempts": 1},
    )
    assert decision.article_id == article_id
    assert decision.decision_type == "auditor"
    assert decision.outcome == "pass"
    assert decision.details == {"attempts": 1}

    decisions = db_manager.lifecycle.get_editorial_decisions_for_article(article_id)
    assert len(decisions) == 1
    assert decisions[0].id == decision.id


def test_record_editorial_decision_allows_null_article_id(db_manager):
    # EditorialAuditor can audit before a numeric Article row exists — see
    # models.py's EditorialDecision docstring.
    decision = db_manager.lifecycle.record_editorial_decision(
        article_id=None,
        decision_type="auditor",
        outcome="fail",
        decided_at=datetime.now(timezone.utc),
    )
    assert decision.article_id is None
    assert decision.id is not None


def test_editorial_decision_exists(db_manager):
    article_id = _make_article(db_manager, "ed2")
    assert (
        db_manager.lifecycle.editorial_decision_exists(article_id, "auditor") is False
    )
    db_manager.lifecycle.record_editorial_decision(
        article_id=article_id,
        decision_type="auditor",
        outcome="pass",
        decided_at=datetime.now(timezone.utc),
    )
    assert db_manager.lifecycle.editorial_decision_exists(article_id, "auditor") is True
    # Different decision_type, same article: still "not found".
    assert db_manager.lifecycle.editorial_decision_exists(article_id, "critic") is False


# ---------------------------------------------------------------------------
# Legacy audit-state mapping
# ---------------------------------------------------------------------------


def test_map_legacy_audit_outcome_known_values():
    assert map_legacy_audit_outcome("audit_passed") == "pass"
    assert map_legacy_audit_outcome("passed") == "pass"
    assert map_legacy_audit_outcome("audit_failed") == "fail"
    assert map_legacy_audit_outcome("failed") == "fail"


def test_map_legacy_audit_outcome_non_terminal_and_unknown():
    assert map_legacy_audit_outcome("audit_pending") is None
    assert map_legacy_audit_outcome("audit_skipped") is None
    assert map_legacy_audit_outcome("audit_skipped_backpressure") is None
    assert map_legacy_audit_outcome("something_unexpected") is None
    assert map_legacy_audit_outcome(None) is None


def test_audit_legacy_state_to_outcome_only_contains_valid_enum_values():
    # editorial_decisions.outcome CHECK constraint — see models.py
    # EDITORIAL_DECISION_OUTCOME_VALUES.
    valid_outcomes = {"pass", "fail", "accept", "reject"}
    assert set(AUDIT_LEGACY_STATE_TO_OUTCOME.values()) <= valid_outcomes
