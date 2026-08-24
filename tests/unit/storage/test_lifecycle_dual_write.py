"""Tests for the Plan 060 / Phase 3c dual-write wiring in
``DatabaseManager``'s five publication/audit facade methods
(``storage/database.py``).

Fixture-driven, matching test_backfill.py's/test_reconciliation_report.py's
`tmp_path` convention. Each legacy write path is exercised through the
public facade (not the underlying `ArticleRepository` methods directly,
except where a test is specifically about the `on_transition` contract at
that layer) to prove the dual-write seam actually fires from the callers
production code uses.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article, Base

pytestmark = pytest.mark.timeout(15)


@pytest.fixture
def db_manager(tmp_path):
    db_file = tmp_path / "dual_write.db"
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


def _save_article(db_manager, seed: str) -> int:
    payload = {
        "title": f"Dual-write test title {seed}",
        "url": f"https://x.com/{seed}",
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
    saved = db_manager.articles.save_article(payload)
    return int(saved.id)


def _set_legacy_publication(
    db_manager,
    article_id: int,
    *,
    refinery_id: str,
    state: str,
    pr_url: str | None = None,
) -> None:
    """Directly write article_metadata["publication"], bypassing the
    ingestion contract — matches how mark_article_published itself writes
    it (see test_backfill.py's _save_article docstring for the same
    rationale)."""
    with db_manager.get_session() as session:
        article = session.query(Article).filter(Article.id == article_id).first()
        metadata = dict(article.article_metadata or {})
        metadata["publication"] = {
            "state": state,
            "refinery_id": refinery_id,
            "pr_url": pr_url,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        article.article_metadata = metadata
        article.processing_status = "publishing"
        session.add(article)


# ---------------------------------------------------------------------------
# mark_article_publishing
# ---------------------------------------------------------------------------


def test_mark_article_publishing_dual_writes_publishing_row(db_manager):
    article_id = _save_article(db_manager, "publishing")

    result = db_manager.mark_article_publishing(article_id, "content/update-x")

    assert result is True
    rows = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.state == "PUBLISHING"
    assert row.refinery_id == str(article_id)
    assert row.branch_name == "content/update-x"
    assert row.attempt_number == 1


def test_mark_article_publishing_missing_article_no_dual_write(db_manager):
    result = db_manager.mark_article_publishing(999999, "content/update-x")

    assert result is False
    assert db_manager.lifecycle.get_publication_attempts_for_article(999999) == []


def test_mark_article_publishing_swallows_lifecycle_failure(db_manager, monkeypatch):
    article_id = _save_article(db_manager, "publishing-fail")

    def _boom(*args, **kwargs):
        raise RuntimeError("lifecycle write exploded")

    monkeypatch.setattr(db_manager.lifecycle, "record_publication_attempt", _boom)

    result = db_manager.mark_article_publishing(article_id, "content/update-x")

    # Legacy write is the source of truth and must still succeed.
    assert result is True


# ---------------------------------------------------------------------------
# mark_article_published
# ---------------------------------------------------------------------------


def test_mark_article_published_cas_transitions_publishing_row(db_manager):
    article_id = _save_article(db_manager, "published-cas")
    db_manager.mark_article_publishing(article_id, "content/update-y")

    result = db_manager.mark_article_published(article_id, "https://github.com/pr/1")

    assert result is True
    rows = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    assert len(rows) == 1  # transitioned in place, not a new row
    row = rows[0]
    assert row.state == "PR_CREATED"
    assert row.pr_url == "https://github.com/pr/1"
    assert row.refinery_id == str(article_id)
    assert row.branch_name == "content/update-y"  # preserved from the CAS


def test_mark_article_published_without_prior_publishing_inserts_fresh_row(db_manager):
    """Matches the real defensive `hasattr` caller in refinery_engine.py,
    which can skip mark_article_publishing entirely."""
    article_id = _save_article(db_manager, "published-fresh")

    result = db_manager.mark_article_published(article_id, "https://github.com/pr/2")

    assert result is True
    rows = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.state == "PR_CREATED"
    assert row.pr_url == "https://github.com/pr/2"
    assert row.refinery_id == str(article_id)
    assert row.attempt_number == 1


def test_mark_article_published_cas_miss_falls_back_to_fresh_row(db_manager):
    """A CAS miss (the PUBLISHING row already transitioned by someone else)
    must still leave a PR_CREATED row behind."""
    article_id = _save_article(db_manager, "published-cas-miss")
    db_manager.mark_article_publishing(article_id, "content/update-z")

    rows = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    attempt_id = rows[0].id
    # Simulate someone else already transitioning this row out from under us.
    transitioned = db_manager.lifecycle.transition_publication_attempt(
        attempt_id,
        from_state="PUBLISHING",
        to_state="PR_CREATED",
        pr_url="https://x/other",
    )
    assert transitioned is True

    result = db_manager.mark_article_published(article_id, "https://github.com/pr/3")

    assert result is True
    rows = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    # Original row (now PR_CREATED via the simulated race) plus a fresh
    # fallback row for this call's own PR_CREATED event.
    assert len(rows) == 2
    states = sorted(r.state for r in rows)
    assert states == ["PR_CREATED", "PR_CREATED"]
    assert any(r.pr_url == "https://github.com/pr/3" for r in rows)


def test_mark_article_published_swallows_lifecycle_failure(db_manager, monkeypatch):
    article_id = _save_article(db_manager, "published-fail")

    def _boom(*args, **kwargs):
        raise RuntimeError("lifecycle read exploded")

    monkeypatch.setattr(
        db_manager.lifecycle, "get_publication_attempts_for_article", _boom
    )

    result = db_manager.mark_article_published(article_id, "https://github.com/pr/4")

    assert result is True


# ---------------------------------------------------------------------------
# reject_publication_attempts / complete_publication_attempts
# ---------------------------------------------------------------------------


def test_reject_publication_attempts_dual_writes_transition(db_manager):
    article_id = _save_article(db_manager, "reject")
    db_manager.mark_article_publishing(article_id, "content/update-r")
    db_manager.mark_article_published(article_id, "https://github.com/pr/5")

    updated = db_manager.reject_publication_attempts(
        [str(article_id)], reason="Content Guard failed"
    )

    assert updated == 1
    rows = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    assert len(rows) == 1
    assert rows[0].state == "REJECTED"


def test_complete_publication_attempts_dual_writes_transition(db_manager):
    article_id = _save_article(db_manager, "complete")
    db_manager.mark_article_publishing(article_id, "content/update-c")
    db_manager.mark_article_published(article_id, "https://github.com/pr/6")

    updated = db_manager.complete_publication_attempts(
        [str(article_id)], "https://noticiencias.com/live/6"
    )

    assert updated == 1
    rows = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    assert len(rows) == 1
    assert rows[0].state == "COMPLETED"


def test_reject_reads_actual_current_state_not_assumed_pr_created(db_manager):
    """A webhook can race ahead of mark_article_published's own dual-write
    (e.g. that call's lifecycle write failed/is still pending) — the
    publication_attempts row can legitimately still be PUBLISHING when the
    reject/complete dual-write fires. It must CAS from the row's *actual*
    state, not assume PR_CREATED."""
    article_id = _save_article(db_manager, "reject-race")
    db_manager.mark_article_publishing(article_id, "content/update-race")
    # Legacy metadata has already moved on to PR_CREATED (as it would once
    # mark_article_published's own *legacy* write ran), but the lifecycle
    # row is deliberately left in PUBLISHING to simulate that call's
    # dual-write half failing.
    _set_legacy_publication(
        db_manager,
        article_id,
        refinery_id=str(article_id),
        state="PR_CREATED",
        pr_url="https://github.com/pr/7",
    )

    rows = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    assert rows[0].state == "PUBLISHING"  # sanity: race actually set up

    updated = db_manager.reject_publication_attempts(
        [str(article_id)], reason="raced rejection"
    )

    assert updated == 1
    rows = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    assert rows[0].state == "REJECTED"  # CAS'd from PUBLISHING, not skipped


def test_reject_publication_attempts_swallows_lifecycle_failure(
    db_manager, monkeypatch
):
    article_id = _save_article(db_manager, "reject-fail")
    db_manager.mark_article_publishing(article_id, "content/update-rf")
    db_manager.mark_article_published(article_id, "https://github.com/pr/8")

    def _boom(*args, **kwargs):
        raise RuntimeError("lifecycle transition exploded")

    monkeypatch.setattr(db_manager.lifecycle, "transition_publication_attempt", _boom)

    updated = db_manager.reject_publication_attempts(
        [str(article_id)], reason="whatever"
    )

    # Legacy transition must still be reported, even though the lifecycle
    # CAS raised internally.
    assert updated == 1


# ---------------------------------------------------------------------------
# ArticleRepository.on_transition contract (article_repository.py layer)
# ---------------------------------------------------------------------------


def test_article_repository_reject_on_transition_none_is_unaffected(db_manager):
    """Regression test: calling with on_transition omitted (exactly as
    today's three existing callers do) must be byte-identical to before
    this phase — same return value, same legacy mutation."""
    article_id = _save_article(db_manager, "on-transition-none")
    db_manager.articles.mark_article_publishing(article_id, "content/update-n")
    db_manager.articles.mark_article_published(
        article_id, "https://github.com/pr/9", None
    )

    updated = db_manager.articles.reject_publication_attempts(
        [str(article_id)], reason="no callback"
    )

    assert updated == 1
    with db_manager.get_session() as session:
        article = session.query(Article).filter(Article.id == article_id).first()
        assert article.processing_status == "rejected"
        assert article.article_metadata["publication"]["state"] == "REJECTED"


def test_on_transition_callback_exception_does_not_propagate_or_stop_loop(db_manager):
    article_a = _save_article(db_manager, "cb-a")
    article_b = _save_article(db_manager, "cb-b")
    for aid in (article_a, article_b):
        db_manager.articles.mark_article_publishing(aid, f"content/update-{aid}")
        db_manager.articles.mark_article_published(
            aid, f"https://github.com/pr/{aid}", None
        )

    calls: list[tuple[int, str]] = []

    def _raising_callback(article_id: int, refinery_id: str) -> None:
        calls.append((article_id, refinery_id))
        raise RuntimeError("callback exploded")

    updated = db_manager.articles.reject_publication_attempts(
        [str(article_a), str(article_b)],
        reason="both",
        on_transition=_raising_callback,
    )

    # Both articles transitioned in the legacy DB despite the callback
    # raising every time — the exception never propagated and never
    # stopped the loop from processing the remaining article.
    assert updated == 2
    assert len(calls) == 2
    with db_manager.get_session() as session:
        for aid in (article_a, article_b):
            article = session.query(Article).filter(Article.id == aid).first()
            assert article.processing_status == "rejected"


# ---------------------------------------------------------------------------
# update_article_audit_status
# ---------------------------------------------------------------------------


def test_update_article_audit_status_dual_writes_editorial_decision(db_manager):
    article_id = _save_article(db_manager, "audit-pass")

    result = db_manager.update_article_audit_status(
        article_id,
        "audit_passed",
        "looks good",
        attempts=2,
        timeout_seconds=30,
        model="llama3.2",
        endpoint="local",
    )

    assert result is True
    rows = db_manager.lifecycle.get_editorial_decisions_for_article(article_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.decision_type == "auditor"
    assert row.outcome == "pass"
    assert row.reason == "looks good"
    assert row.details["legacy_state"] == "audit_passed"
    assert row.details["attempts"] == 2
    assert row.details["timeout_seconds"] == 30
    assert row.details["model"] == "llama3.2"
    assert row.details["endpoint"] == "local"


def test_update_article_audit_status_non_terminal_produces_no_row(db_manager):
    article_id = _save_article(db_manager, "audit-pending")

    result = db_manager.update_article_audit_status(article_id, "audit_pending", "")

    assert result is True
    assert db_manager.lifecycle.get_editorial_decisions_for_article(article_id) == []


def test_update_article_audit_status_missing_article_no_dual_write(db_manager):
    result = db_manager.update_article_audit_status(999999, "audit_passed", "")

    assert result is False
    assert db_manager.lifecycle.get_editorial_decisions_for_article(999999) == []


def test_update_article_audit_status_swallows_lifecycle_failure(
    db_manager, monkeypatch
):
    article_id = _save_article(db_manager, "audit-fail")

    def _boom(*args, **kwargs):
        raise RuntimeError("lifecycle audit write exploded")

    monkeypatch.setattr(db_manager.lifecycle, "record_editorial_decision", _boom)

    result = db_manager.update_article_audit_status(article_id, "audit_failed", "bad")

    assert result is True
