"""Tests for scripts/lifecycle_reconciliation_report.py (Plan 060 / Phase 3b).

Fixture-driven, matching test_backfill.py's `tmp_path` convention. Confirms
the report is read-only and correctly distinguishes "drift" (a real
mismatch) from "missing" (legacy data exists, no new-table row does) from
"not_applicable" (a non-terminal legacy audit state that was correctly
never backfilled).
"""

from datetime import datetime, timezone

import pytest

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article, Base
from scripts.backfill_lifecycle_tables import backfill
from scripts.lifecycle_reconciliation_report import reconcile


@pytest.fixture
def db_manager(tmp_path):
    db_file = tmp_path / "reconcile.db"
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
    """See test_backfill.py's `_save_article` docstring: `article_metadata`
    is written via a raw session after save, matching how the real
    `mark_article_published`/`update_article_audit_status` write paths
    populate it (never through the ingestion contract, which forbids these
    keys)."""
    payload = {
        "title": f"Reconciliation test title {seed}",
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


def test_reconcile_reports_clean_after_backfill(db_manager):
    _save_article(
        db_manager,
        "clean",
        article_metadata={
            "publication": {
                "state": "COMPLETED",
                "pr_url": "https://example.com/pr/9",
                "refinery_id": "ref-clean",
                "updated_at": "2026-01-01T00:00:00+00:00",
            },
            "audit": {
                "state": "audit_passed",
                "reason": "ok",
                "updated_at": "2026-01-01T00:00:00+00:00",
            },
        },
    )
    backfill(db_manager)

    summary = reconcile(db_manager)

    counts = summary.counts()
    assert counts["drift"] == 0
    assert counts["missing"] == 0
    assert counts["clean"] == 2  # one publication check + one audit check
    assert summary.ok() is True


def test_reconcile_reports_missing_when_backfill_never_ran(db_manager):
    _save_article(
        db_manager,
        "missing",
        article_metadata={
            "publication": {
                "state": "PR_CREATED",
                "refinery_id": "ref-missing",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        },
    )
    # Deliberately do not call backfill().

    summary = reconcile(db_manager)

    assert summary.counts()["missing"] == 1
    assert summary.ok() is False
    [check] = summary.checks
    assert check.status == "missing"
    assert check.kind == "publication"


def test_reconcile_reports_drift_on_deliberate_mismatch(db_manager):
    article_id = _save_article(
        db_manager,
        "drift",
        article_metadata={
            "publication": {
                "state": "COMPLETED",
                "pr_url": "https://example.com/pr/original",
                "refinery_id": "ref-drift",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        },
    )
    backfill(db_manager)

    # Simulate drift: mutate the legacy blob after backfill so it no longer
    # agrees with the already-backfilled row (e.g. a manual DB edit, or a
    # bug in some other writer).
    with db_manager.get_session() as session:
        article = session.query(Article).filter(Article.id == article_id).first()
        metadata = dict(article.article_metadata)
        metadata["publication"] = dict(metadata["publication"])
        metadata["publication"]["pr_url"] = "https://example.com/pr/CHANGED"
        article.article_metadata = metadata
        session.add(article)

    summary = reconcile(db_manager)

    assert summary.counts()["drift"] == 1
    assert summary.ok() is False
    [check] = summary.checks
    assert check.status == "drift"
    assert "pr_url" in check.detail


def test_reconcile_not_applicable_for_non_terminal_audit_state(db_manager):
    _save_article(
        db_manager,
        "pending",
        article_metadata={"audit": {"state": "audit_pending"}},
    )
    backfill(db_manager)  # correctly creates nothing for this audit blob

    summary = reconcile(db_manager)

    counts = summary.counts()
    assert counts["not_applicable"] == 1
    assert counts["missing"] == 0
    assert counts["drift"] == 0
    # not_applicable does not affect ok() — only drift/missing do.
    assert summary.ok() is True


def test_reconcile_is_read_only(db_manager):
    article_id = _save_article(
        db_manager,
        "readonly",
        article_metadata={
            "publication": {
                "state": "PR_CREATED",
                "refinery_id": "ref-readonly",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        },
    )
    # Deliberately do not backfill — this should report "missing" without
    # writing anything.
    reconcile(db_manager)

    assert db_manager.lifecycle.get_publication_attempts_for_article(article_id) == []
    with db_manager.get_session() as session:
        from news_collector.storage.models import PublicationAttemptRecord

        assert session.query(PublicationAttemptRecord).count() == 0
