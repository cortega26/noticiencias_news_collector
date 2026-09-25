"""Unit tests for the Phase 5b publication-attempt audit:

- the explicit legal-transition map,
- ``apply_publication_transition`` (legality + CAS + event atomically),
- append-only ``publication_events`` reads,
- the reconciler's lookup/stale-scan queries.

Real SQLite through ``DatabaseManager``, matching
``tests/unit/storage/test_lifecycle_repository.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from news_collector.storage.database import DatabaseManager
from news_collector.storage.lifecycle_repository import (
    LEGAL_PUBLICATION_TRANSITIONS,
    is_legal_publication_transition,
)
from news_collector.storage.models import Base


@pytest.fixture
def db_manager(tmp_path):
    db_file = tmp_path / "lifecycle_events.db"
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
        "title": f"Publication events test {seed}",
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
        _article_payload(f"https://x.com/events/{seed}", seed)
    )
    return int(saved.id)


def _make_attempt(
    db_manager, article_id, *, refinery_id="ref-1", state="PR_CREATED", started_at=None
):
    return db_manager.lifecycle.record_publication_attempt(
        article_id,
        refinery_id=refinery_id,
        state=state,
        started_at=started_at or datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Legality map
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "from_state,to_state,expected",
    [
        ("PUBLISHING", "PR_CREATED", True),
        ("PUBLISHING", "REJECTED", True),  # callback race, plan 3c
        ("PUBLISHING", "COMPLETED", True),  # callback race, plan 3c
        ("PR_CREATED", "REJECTED", True),
        ("PR_CREATED", "COMPLETED", True),
        ("PR_CREATED", "PUBLISHING", False),
        ("REJECTED", "COMPLETED", False),
        ("REJECTED", "REJECTED", False),
        ("COMPLETED", "REJECTED", False),
        ("COMPLETED", "COMPLETED", False),
        ("UNKNOWN_STATE", "COMPLETED", False),
        ("PR_CREATED", "UNKNOWN_STATE", False),
    ],
)
def test_legal_transition_truth_table(from_state, to_state, expected):
    assert is_legal_publication_transition(from_state, to_state) is expected


def test_terminal_states_permit_nothing():
    assert LEGAL_PUBLICATION_TRANSITIONS["REJECTED"] == frozenset()
    assert LEGAL_PUBLICATION_TRANSITIONS["COMPLETED"] == frozenset()


# ---------------------------------------------------------------------------
# publication_events — append-only
# ---------------------------------------------------------------------------


def test_record_publication_event_round_trips(db_manager):
    article_id = _make_article(db_manager, "evt1")
    attempt = _make_attempt(db_manager, article_id)
    occurred = datetime.now(timezone.utc)

    event = db_manager.lifecycle.record_publication_event(
        attempt.id,
        event_type="check_passed",
        occurred_at=occurred,
        details={"commit_sha": "abc123", "branch": "content/update-x"},
    )

    assert event.publication_attempt_id == attempt.id
    assert event.event_type == "check_passed"
    assert event.details == {"commit_sha": "abc123", "branch": "content/update-x"}

    [reloaded] = db_manager.lifecycle.get_publication_events_for_attempt(attempt.id)
    assert reloaded.id == event.id
    assert reloaded.event_type == "check_passed"


def test_record_publication_event_rejects_unknown_type(db_manager):
    article_id = _make_article(db_manager, "evt2")
    attempt = _make_attempt(db_manager, article_id)

    with pytest.raises(ValueError):
        db_manager.lifecycle.record_publication_event(
            attempt.id, event_type="not_a_real_type"
        )

    assert db_manager.lifecycle.get_publication_events_for_attempt(attempt.id) == []


# ---------------------------------------------------------------------------
# apply_publication_transition
# ---------------------------------------------------------------------------


def test_apply_transition_writes_state_and_exactly_one_event(db_manager):
    article_id = _make_article(db_manager, "apply1")
    attempt = _make_attempt(db_manager, article_id)
    finished = datetime.now(timezone.utc)

    ok = db_manager.lifecycle.apply_publication_transition(
        attempt.id,
        from_state="PR_CREATED",
        to_state="COMPLETED",
        event_type="deployed",
        details={"deploy_url": "https://noticiencias.com"},
        finished_at=finished,
    )

    assert ok is True
    [reloaded] = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    assert reloaded.state == "COMPLETED"
    assert reloaded.finished_at is not None
    events = db_manager.lifecycle.get_publication_events_for_attempt(attempt.id)
    assert len(events) == 1
    assert events[0].event_type == "deployed"
    assert events[0].details == {"deploy_url": "https://noticiencias.com"}


def test_apply_transition_cas_miss_appends_no_event(db_manager):
    article_id = _make_article(db_manager, "apply2")
    attempt = _make_attempt(db_manager, article_id, state="REJECTED")

    ok = db_manager.lifecycle.apply_publication_transition(
        attempt.id,
        from_state="PR_CREATED",  # stale expectation; row is REJECTED
        to_state="COMPLETED",
        event_type="deployed",
    )

    assert ok is False
    assert db_manager.lifecycle.get_publication_events_for_attempt(attempt.id) == []


def test_apply_transition_illegal_pair_writes_nothing(db_manager):
    article_id = _make_article(db_manager, "apply3")
    attempt = _make_attempt(db_manager, article_id, state="REJECTED")

    ok = db_manager.lifecycle.apply_publication_transition(
        attempt.id,
        from_state="REJECTED",
        to_state="COMPLETED",
        event_type="deployed",
    )

    assert ok is False
    [reloaded] = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    assert reloaded.state == "REJECTED"
    assert db_manager.lifecycle.get_publication_events_for_attempt(attempt.id) == []


def test_apply_transition_unknown_event_type_writes_nothing(db_manager):
    article_id = _make_article(db_manager, "apply4")
    attempt = _make_attempt(db_manager, article_id)

    ok = db_manager.lifecycle.apply_publication_transition(
        attempt.id,
        from_state="PR_CREATED",
        to_state="COMPLETED",
        event_type="not_a_real_type",
    )

    assert ok is False
    [reloaded] = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    assert reloaded.state == "PR_CREATED"
    assert db_manager.lifecycle.get_publication_events_for_attempt(attempt.id) == []


# ---------------------------------------------------------------------------
# Reconciler queries
# ---------------------------------------------------------------------------


def test_find_latest_attempt_by_refinery_id_prefers_newest(db_manager):
    article_id = _make_article(db_manager, "find1")
    _make_attempt(db_manager, article_id, refinery_id="ref-a", state="REJECTED")
    newest = _make_attempt(
        db_manager, article_id, refinery_id="ref-a", state="PR_CREATED"
    )

    found = db_manager.lifecycle.find_latest_publication_attempt_by_refinery_id("ref-a")

    assert found is not None
    assert found.id == newest.id
    assert (
        db_manager.lifecycle.find_latest_publication_attempt_by_refinery_id("nope")
        is None
    )


def test_list_stale_attempts_filters_state_age_and_limit(db_manager):
    article_id = _make_article(db_manager, "stale1")
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=3)

    stale = _make_attempt(db_manager, article_id, refinery_id="r-old", started_at=old)
    _make_attempt(
        db_manager, article_id, refinery_id="r-new", started_at=now
    )  # too fresh
    _make_attempt(
        db_manager,
        article_id,
        refinery_id="r-done",
        state="COMPLETED",
        started_at=old,
    )  # terminal, not a candidate

    candidates = db_manager.lifecycle.list_stale_publication_attempts(
        older_than=now - timedelta(hours=1)
    )
    assert [c.id for c in candidates] == [stale.id]

    limited = db_manager.lifecycle.list_stale_publication_attempts(
        older_than=now - timedelta(hours=1), limit=1
    )
    assert [c.id for c in limited] == [stale.id]

    fresh_cutoff = db_manager.lifecycle.list_stale_publication_attempts(
        older_than=now - timedelta(hours=4)
    )
    assert fresh_cutoff == []
