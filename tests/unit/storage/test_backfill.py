"""Tests for scripts/backfill_lifecycle_tables.py (Plan 060 / Phase 3b).

Per plans/060/phase-3b-typed-repos/spec.md recon finding 6, the local dev
database has never held real publication/audit history, so this backfill is
proven exclusively against synthetic fixture data with known
`article_metadata` shapes — never against the real local database — matching
tests/test_database_migrations.py's `tmp_path`-fixture convention.
"""

from datetime import datetime, timezone

import pytest

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article, Base
from scripts.backfill_lifecycle_tables import backfill


@pytest.fixture
def db_manager(tmp_path):
    db_file = tmp_path / "backfill.db"
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


def _save_article(db_manager, seed, article_metadata=None):
    """Save a plain article, then — for `publication`/`audit` fixture data
    — write `article_metadata` directly via a raw session, bypassing
    `CollectorArticleModel` (whose `ArticleMetadataModel` sub-schema is
    `extra="forbid"` and does not know about `publication`/`audit` keys).
    This matches how the real write paths populate them: `mark_article_published`/
    `update_article_audit_status` (article_repository.py) mutate
    `article.article_metadata` directly, never through the ingestion
    contract — so this is a faithful fixture, not a shortcut around
    validation that production code actually enforces.
    """
    payload = {
        "title": f"Backfill test title {seed}",
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
    article_id = int(saved.id)

    if article_metadata is not None:
        with db_manager.get_session() as session:
            article = session.query(Article).filter(Article.id == article_id).first()
            merged = dict(article.article_metadata or {})
            merged.update(article_metadata)
            article.article_metadata = merged
            session.add(article)

    return article_id


def test_backfill_article_with_both_publication_and_audit(db_manager):
    article_id = _save_article(
        db_manager,
        "both",
        article_metadata={
            "publication": {
                "state": "COMPLETED",
                "pr_url": "https://example.com/pr/1",
                "refinery_id": "ref-both",
                "frontend_checks": {
                    "state": "ready_for_merge",
                    "ready_for_merge": True,
                },
                "updated_at": "2026-01-01T00:00:00+00:00",
            },
            "audit": {
                "state": "audit_passed",
                "reason": "solid",
                "updated_at": "2026-01-01T01:00:00+00:00",
                "attempts": 1,
                "model": "test-model",
            },
        },
    )

    summary = backfill(db_manager)

    assert summary.articles_processed == 1
    assert summary.publication_rows_created == 1
    assert summary.audit_rows_created == 1
    assert summary.skipped_no_legacy_data == 0

    [pub] = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    assert pub.refinery_id == "ref-both"
    assert pub.state == "COMPLETED"
    assert pub.pr_url == "https://example.com/pr/1"
    assert pub.attempt_number == 1
    assert pub.details == {
        "frontend_checks": {"state": "ready_for_merge", "ready_for_merge": True}
    }
    assert pub.finished_at is not None  # terminal state

    [decision] = db_manager.lifecycle.get_editorial_decisions_for_article(article_id)
    assert decision.decision_type == "auditor"
    assert decision.outcome == "pass"
    assert decision.reason == "solid"
    assert decision.details["legacy_state"] == "audit_passed"
    assert decision.details["attempts"] == 1
    assert decision.details["model"] == "test-model"


def test_backfill_article_with_only_publication(db_manager):
    article_id = _save_article(
        db_manager,
        "pub-only",
        article_metadata={
            "publication": {
                "state": "PR_CREATED",
                "pr_url": "https://example.com/pr/2",
                "refinery_id": "ref-pub-only",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        },
    )

    summary = backfill(db_manager)

    assert summary.publication_rows_created == 1
    assert summary.audit_rows_created == 0
    [pub] = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    assert pub.state == "PR_CREATED"
    assert pub.finished_at is None  # not terminal
    assert db_manager.lifecycle.get_editorial_decisions_for_article(article_id) == []


def test_backfill_article_with_neither_is_skipped(db_manager):
    article_id = _save_article(db_manager, "neither")

    summary = backfill(db_manager)

    assert summary.articles_processed == 1
    assert summary.skipped_no_legacy_data == 1
    assert summary.publication_rows_created == 0
    assert summary.audit_rows_created == 0
    assert db_manager.lifecycle.get_publication_attempts_for_article(article_id) == []
    assert db_manager.lifecycle.get_editorial_decisions_for_article(article_id) == []


def test_backfill_is_idempotent(db_manager):
    _save_article(
        db_manager,
        "idempotent",
        article_metadata={
            "publication": {
                "state": "PR_CREATED",
                "refinery_id": "ref-idem",
                "updated_at": "2026-01-01T00:00:00+00:00",
            },
            "audit": {
                "state": "audit_failed",
                "updated_at": "2026-01-01T00:00:00+00:00",
            },
        },
    )

    first = backfill(db_manager)
    assert first.publication_rows_created == 1
    assert first.audit_rows_created == 1

    second = backfill(db_manager)
    assert second.publication_rows_created == 0
    assert second.audit_rows_created == 0
    assert second.already_migrated_publication == 1
    assert second.already_migrated_audit == 1


def test_backfill_degraded_legacy_blob_missing_optional_key_does_not_crash(db_manager):
    # `updated_at` (used for started_at/decided_at, both NOT NULL columns)
    # is absent — the backfill must fall back to article.collected_date,
    # not crash.
    article_id = _save_article(
        db_manager,
        "degraded",
        article_metadata={
            "publication": {"state": "PR_CREATED", "refinery_id": "ref-degraded"},
            "audit": {"state": "audit_passed"},
        },
    )

    summary = backfill(db_manager)

    assert summary.publication_rows_created == 1
    assert summary.audit_rows_created == 1
    [pub] = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    assert pub.started_at is not None
    [decision] = db_manager.lifecycle.get_editorial_decisions_for_article(article_id)
    assert decision.decided_at is not None


def test_backfill_missing_refinery_id_falls_back_to_article_id(db_manager):
    article_id = _save_article(
        db_manager,
        "no-refinery-id",
        article_metadata={
            "publication": {
                "state": "COMPLETED",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        },
    )

    backfill(db_manager)

    [pub] = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    assert pub.refinery_id == str(article_id)


def test_backfill_non_terminal_audit_state_creates_no_row(db_manager):
    article_id = _save_article(
        db_manager,
        "pending-audit",
        article_metadata={"audit": {"state": "audit_pending"}},
    )

    summary = backfill(db_manager)

    assert summary.audit_rows_created == 0
    assert summary.audit_state_not_decision == 1
    assert db_manager.lifecycle.get_editorial_decisions_for_article(article_id) == []


def test_backfill_invalid_publication_state_creates_no_row(db_manager):
    article_id = _save_article(
        db_manager,
        "bad-pub-state",
        article_metadata={"publication": {"state": "SOMETHING_UNKNOWN"}},
    )

    summary = backfill(db_manager)

    assert summary.publication_rows_created == 0
    assert summary.publication_state_invalid == 1
    assert db_manager.lifecycle.get_publication_attempts_for_article(article_id) == []


def test_backfill_deterministic_across_reruns_no_now_fallback(db_manager):
    # Regression guard: the fallback timestamp for a missing updated_at
    # must be article.collected_date, not datetime.now() — otherwise
    # re-running the backfill against the same degraded row would produce
    # a different started_at each time (it can't, because of the
    # idempotency check, but the *first* run's value must still be
    # reproducible/deterministic given the same article row).
    article_id = _save_article(
        db_manager,
        "deterministic",
        article_metadata={"publication": {"state": "PR_CREATED", "refinery_id": "r"}},
    )
    with db_manager.get_session() as session:
        from news_collector.storage.models import Article

        article = session.query(Article).filter(Article.id == article_id).first()
        collected_date = article.collected_date

    backfill(db_manager)

    [pub] = db_manager.lifecycle.get_publication_attempts_for_article(article_id)
    assert pub.started_at == collected_date
