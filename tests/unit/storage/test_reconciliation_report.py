"""Tests for scripts/lifecycle_reconciliation_report.py (Plan 060 / Phase 3b,
extended in Phase 3c with the ``--dual-write-since`` split).

Fixture-driven, matching test_backfill.py's `tmp_path` convention. Confirms
the report is read-only and correctly distinguishes "drift" (a real
mismatch) from "missing" (legacy data exists, no new-table row does) from
"not_applicable" (a non-terminal legacy audit state that was correctly
never backfilled), plus (Phase 3c) "missing_pre_dualwrite"/
"missing_post_dualwrite" when ``--dual-write-since`` is given.
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


def _set_collected_date(db_manager, article_id, collected_date):
    with db_manager.get_session() as session:
        article = session.query(Article).filter(Article.id == article_id).first()
        article.collected_date = collected_date
        session.add(article)


def test_reconcile_dual_write_since_splits_missing_into_pre_and_post(db_manager):
    cutover = datetime(2026, 6, 1, tzinfo=timezone.utc)

    pre_id = _save_article(
        db_manager,
        "pre-cutover",
        article_metadata={
            "publication": {
                "state": "PR_CREATED",
                "refinery_id": "ref-pre",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        },
    )
    _set_collected_date(db_manager, pre_id, datetime(2026, 5, 1, tzinfo=timezone.utc))

    post_id = _save_article(
        db_manager,
        "post-cutover",
        article_metadata={
            "publication": {
                "state": "PR_CREATED",
                "refinery_id": "ref-post",
                "updated_at": "2026-07-01T00:00:00+00:00",
            }
        },
    )
    _set_collected_date(db_manager, post_id, datetime(2026, 7, 1, tzinfo=timezone.utc))
    # Deliberately do not backfill — both are "missing" before the split.

    summary = reconcile(db_manager, dual_write_since=cutover)

    counts = summary.counts()
    assert counts["missing"] == 0  # raw "missing" no longer used once split
    assert counts["missing_pre_dualwrite"] == 1
    assert counts["missing_post_dualwrite"] == 1
    assert summary.ok() is False  # missing_post_dualwrite is a real failure

    by_article = {c.article_id: c.status for c in summary.checks}
    assert by_article[pre_id] == "missing_pre_dualwrite"
    assert by_article[post_id] == "missing_post_dualwrite"


def test_reconcile_dual_write_since_pre_only_does_not_fail(db_manager):
    cutover = datetime(2026, 6, 1, tzinfo=timezone.utc)

    pre_id = _save_article(
        db_manager,
        "pre-only",
        article_metadata={
            "publication": {
                "state": "PR_CREATED",
                "refinery_id": "ref-pre-only",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        },
    )
    _set_collected_date(db_manager, pre_id, datetime(2026, 3, 1, tzinfo=timezone.utc))

    summary = reconcile(db_manager, dual_write_since=cutover)

    counts = summary.counts()
    assert counts["missing_pre_dualwrite"] == 1
    assert counts.get("missing_post_dualwrite", 0) == 0
    # Known, routine pre-existing backfill gap — must not fail the run.
    assert summary.ok() is True


def test_reconcile_dual_write_since_omitted_keeps_exact_output_shape(db_manager):
    """Omitting the flag must reproduce today's exact single-'missing'-bucket
    behavior — same assertions as
    test_reconcile_reports_missing_when_backfill_never_ran, run again here
    to pin the "omitted flag = unchanged shape" contract explicitly next to
    the new split tests above."""
    _save_article(
        db_manager,
        "omitted-flag",
        article_metadata={
            "publication": {
                "state": "PR_CREATED",
                "refinery_id": "ref-omitted",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        },
    )

    summary = reconcile(db_manager)  # no dual_write_since

    counts = summary.counts()
    assert counts["missing"] == 1
    # Exact key set, not just "the two new keys happen to be absent" — the
    # latter would pass trivially even if a future change accidentally
    # pre-seeded them, since _split_missing_status already no-ops here by
    # construction. This is the actual "unchanged shape" assertion.
    assert set(counts) == {"clean", "drift", "missing", "not_applicable"}
    assert summary.ok() is False


def test_reconcile_audit_compares_against_newest_decision_not_oldest(db_manager):
    """Plan 060 / Phase 3c: dual-write's update_article_audit_status has no
    idempotency guard, so more than one 'auditor' editorial_decisions row
    can now exist per article (a retry, or a second admin action). Legacy
    article_metadata["audit"] only ever reflects the *current* (most
    recent) decision, so the reconciliation check must compare against the
    newest row — comparing against the oldest would report spurious drift
    here even though nothing is actually wrong."""
    article_id = _save_article(
        db_manager,
        "multi-decision",
        article_metadata={
            "audit": {
                "state": "audit_passed",
                "reason": "second pass, looks good now",
                "updated_at": "2026-02-01T00:00:00+00:00",
            }
        },
    )
    # Two decisions for the same article, oldest first — simulating a
    # retried audit. The reason on the *older* row deliberately does not
    # match current legacy metadata; only the newer one does.
    db_manager.lifecycle.record_editorial_decision(
        article_id=article_id,
        decision_type="auditor",
        outcome="fail",
        reason="first pass, needs work",
        decided_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db_manager.lifecycle.record_editorial_decision(
        article_id=article_id,
        decision_type="auditor",
        outcome="pass",
        reason="second pass, looks good now",
        decided_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    summary = reconcile(db_manager)

    [check] = [c for c in summary.checks if c.kind == "audit"]
    assert check.status == "clean", check.detail


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
