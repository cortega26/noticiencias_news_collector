"""Identity resolver tests for reader reports (plan 185).

Real SQLite via ``DatabaseManager``; the resolver itself is read-only and
must return a typed unresolved/ambiguous outcome instead of guessing.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from news_collector.logic.workflows.reader_reports import (
    REASON_AMBIGUOUS,
    REASON_INVALID_URL,
    REASON_NO_MATCH,
    REASON_RESOLVED,
    REASON_UNSUPPORTED_HOST,
    REASON_UNSUPPORTED_SCHEME,
    PublishedUrlError,
    normalize_published_url,
    resolve_report_identity,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import (
    Article,
    PublicationAttemptRecord,
    ReaderReport,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
STAGE = "publication_content_fingerprint"


@pytest.fixture
def db_manager(tmp_path):
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "resolver.db"})
    yield manager
    manager.close()


def _seed_article(
    db: DatabaseManager,
    *,
    url: str = "https://example.com/source",
    published_url: str | None = "https://noticiencias.com/posts/example",
    content_hash: str | None = None,
) -> int:
    with db.SessionLocal() as session:
        article = Article(
            url=url,
            title="Example article",
            source_id="test_source",
            source_name="Test Source",
            published_url=published_url,
            content_hash=content_hash,
        )
        session.add(article)
        session.commit()
        return article.id


def _seed_attempt(
    db: DatabaseManager,
    article_id: int,
    *,
    attempt_number: int,
    details: object,
) -> None:
    with db.SessionLocal() as session:
        session.add(
            PublicationAttemptRecord(
                article_id=article_id,
                refinery_id=str(article_id),
                attempt_number=attempt_number,
                state="COMPLETED",
                started_at=NOW,
                finished_at=NOW,
                details=details,
            )
        )
        session.commit()


def _fingerprint_details(digest: str) -> dict[str, object]:
    return {
        "stages": [
            {"name": "write_file", "success": True, "details": {}},
            {
                "name": STAGE,
                "success": True,
                "details": {"content_sha256": digest},
            },
        ]
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "https://noticiencias.com/posts/example",
            "https://noticiencias.com/posts/example",
        ),
        (
            "HTTPS://Noticiencias.COM/posts/Example/",
            "https://noticiencias.com/posts/Example",
        ),
        (
            "https://www.noticiencias.com/posts/example/",
            "https://www.noticiencias.com/posts/example",
        ),
        (
            "https://noticiencias.com/posts/example/?utm_source=x#comments",
            "https://noticiencias.com/posts/example",
        ),
        ("https://noticiencias.com/", "https://noticiencias.com"),
        ("http://noticiencias.com:80/x", "http://noticiencias.com/x"),
        ("https://noticiencias.com:443/x", "https://noticiencias.com/x"),
        ("https://noticiencias.com:8443/x", "https://noticiencias.com:8443/x"),
    ],
)
def test_normalize_published_url(raw: str, expected: str) -> None:
    assert normalize_published_url(raw) == expected


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("", REASON_INVALID_URL),
        ("noticiencias.com/posts/x", REASON_INVALID_URL),
        ("https://noticiencias.com/posts x", REASON_INVALID_URL),
        ("https://noticiencias.com:abc/x", REASON_INVALID_URL),
        ("https:///posts/x", REASON_INVALID_URL),
        ("ftp://noticiencias.com/posts/x", REASON_UNSUPPORTED_SCHEME),
        ("javascript:alert(1)", REASON_UNSUPPORTED_SCHEME),
        ("https://example.com/posts/x", REASON_UNSUPPORTED_HOST),
        ("https://noticiencias.com.evil.example/x", REASON_UNSUPPORTED_HOST),
        ("https://evilnoticiencias.com/x", REASON_UNSUPPORTED_HOST),
    ],
)
def test_normalize_rejects_with_typed_reason(raw: str, reason: str) -> None:
    with pytest.raises(PublishedUrlError) as exc_info:
        normalize_published_url(raw)
    assert exc_info.value.reason == reason


class TestResolutionMatrix:
    def test_exact_url_resolves_to_article_and_revision(
        self, db_manager: DatabaseManager
    ):
        article_id = _seed_article(
            db_manager,
            published_url="https://noticiencias.com/posts/example",
            content_hash="c" * 64,
        )

        identity = resolve_report_identity(
            "https://noticiencias.com/posts/example", db_manager
        )

        assert identity.status == "resolved"
        assert identity.reason == REASON_RESOLVED
        assert identity.refinery_id == str(article_id)
        assert identity.canonical_url == "https://noticiencias.com/posts/example"
        assert identity.content_sha256 == "c" * 64

    @pytest.mark.parametrize(
        "reported_url",
        [
            "https://noticiencias.com/posts/example/",
            "https://noticiencias.com/posts/example?utm_source=newsletter",
            "https://noticiencias.com/posts/example#correction",
            "https://NOTICIENCIAS.COM/posts/example",
        ],
    )
    def test_input_normalization_variants_resolve(
        self, db_manager: DatabaseManager, reported_url: str
    ):
        article_id = _seed_article(db_manager)

        identity = resolve_report_identity(reported_url, db_manager)

        assert identity.status == "resolved"
        assert identity.refinery_id == str(article_id)

    @pytest.mark.parametrize(
        "stored_url",
        [
            "https://noticiencias.com/posts/example/",
            "https://Noticiencias.com/posts/example?utm=1#x",
            "HTTP://noticiencias.com/posts/example",
        ],
    )
    def test_stored_url_is_normalized_before_matching(
        self, db_manager: DatabaseManager, stored_url: str
    ):
        article_id = _seed_article(db_manager, published_url=stored_url)

        identity = resolve_report_identity(
            "https://noticiencias.com/posts/example", db_manager
        )

        assert identity.status == "resolved"
        assert identity.refinery_id == str(article_id)

    def test_http_and_https_are_the_same_revision(self, db_manager: DatabaseManager):
        article_id = _seed_article(
            db_manager, published_url="http://noticiencias.com/posts/example"
        )

        identity = resolve_report_identity(
            "https://noticiencias.com/posts/example", db_manager
        )

        assert identity.status == "resolved"
        assert identity.refinery_id == str(article_id)
        assert identity.canonical_url == "http://noticiencias.com/posts/example"

    def test_no_match_is_unresolved(self, db_manager: DatabaseManager):
        _seed_article(db_manager)

        identity = resolve_report_identity(
            "https://noticiencias.com/posts/other", db_manager
        )

        assert identity.status == "unresolved"
        assert identity.reason == REASON_NO_MATCH
        assert identity.refinery_id is None
        assert identity.canonical_url is None
        assert identity.content_sha256 is None

    def test_legacy_article_without_published_url_is_unresolved(
        self, db_manager: DatabaseManager
    ):
        _seed_article(db_manager, published_url=None)

        identity = resolve_report_identity(
            "https://noticiencias.com/posts/example", db_manager
        )

        assert identity.status == "unresolved"
        assert identity.reason == REASON_NO_MATCH

    def test_two_matching_articles_are_ambiguous(self, db_manager: DatabaseManager):
        _seed_article(
            db_manager,
            url="https://example.com/a",
            published_url="https://noticiencias.com/posts/example",
        )
        _seed_article(
            db_manager,
            url="https://example.com/b",
            published_url="https://noticiencias.com/posts/example/",
        )

        identity = resolve_report_identity(
            "https://noticiencias.com/posts/example", db_manager
        )

        assert identity.status == "ambiguous"
        assert identity.reason == REASON_AMBIGUOUS
        assert identity.refinery_id is None
        assert identity.canonical_url is None

    def test_invalid_or_foreign_url_is_unresolved(self, db_manager: DatabaseManager):
        invalid = resolve_report_identity("nope", db_manager)
        foreign = resolve_report_identity(
            "https://example.com/posts/example", db_manager
        )

        assert invalid.status == "unresolved"
        assert invalid.reason == REASON_INVALID_URL
        assert foreign.status == "unresolved"
        assert foreign.reason == REASON_UNSUPPORTED_HOST

    def test_invalid_stored_published_url_is_not_evidence(
        self, db_manager: DatabaseManager
    ):
        _seed_article(
            db_manager,
            url="https://example.com/foreign",
            published_url="https://example.com/posts/example",
        )
        article_id = _seed_article(
            db_manager,
            url="https://example.com/canonical",
            published_url="https://noticiencias.com/posts/example",
        )

        identity = resolve_report_identity(
            "https://noticiencias.com/posts/example", db_manager
        )

        assert identity.status == "resolved"
        assert identity.refinery_id == str(article_id)


class TestContentRevision:
    def test_latest_attempt_stage_wins(self, db_manager: DatabaseManager):
        article_id = _seed_article(db_manager, content_hash="f" * 64)
        _seed_attempt(
            db_manager,
            article_id,
            attempt_number=1,
            details=_fingerprint_details("a" * 64),
        )
        _seed_attempt(
            db_manager,
            article_id,
            attempt_number=2,
            details=_fingerprint_details("b" * 64),
        )

        identity = resolve_report_identity(
            "https://noticiencias.com/posts/example", db_manager
        )

        assert identity.content_sha256 == "b" * 64

    def test_direct_attempt_detail_is_used_when_no_stage_summary(
        self, db_manager: DatabaseManager
    ):
        """``mark_article_published`` writes the digest directly into the
        attempt details; it is real evidence, not a guess."""
        article_id = _seed_article(db_manager, content_hash="f" * 64)
        _seed_attempt(
            db_manager,
            article_id,
            attempt_number=1,
            details={"content_sha256": "d" * 64},
        )

        identity = resolve_report_identity(
            "https://noticiencias.com/posts/example", db_manager
        )

        assert identity.content_sha256 == "d" * 64

    def test_article_content_hash_is_the_fallback(self, db_manager: DatabaseManager):
        article_id = _seed_article(db_manager, content_hash="e" * 64)
        _seed_attempt(
            db_manager,
            article_id,
            attempt_number=1,
            details={"stages": [{"name": "other", "details": {}}]},
        )

        identity = resolve_report_identity(
            "https://noticiencias.com/posts/example", db_manager
        )

        assert identity.content_sha256 == "e" * 64

    def test_stage_with_flat_digest_is_supported(self, db_manager: DatabaseManager):
        article_id = _seed_article(db_manager, content_hash="f" * 64)
        _seed_attempt(
            db_manager,
            article_id,
            attempt_number=1,
            details={
                "stages": [
                    {
                        "name": STAGE,
                        "success": True,
                        "content_sha256": "a" * 64,
                    }
                ]
            },
        )

        identity = resolve_report_identity(
            "https://noticiencias.com/posts/example", db_manager
        )

        assert identity.content_sha256 == "a" * 64

    def test_malformed_stage_entries_are_skipped(self, db_manager: DatabaseManager):
        article_id = _seed_article(db_manager, content_hash="f" * 64)
        _seed_attempt(
            db_manager,
            article_id,
            attempt_number=1,
            details={
                "stages": [
                    {
                        "name": STAGE,
                        "details": {"content_sha256": "a" * 64},
                    },
                    "not-a-stage",
                ]
            },
        )

        identity = resolve_report_identity(
            "https://noticiencias.com/posts/example", db_manager
        )

        assert identity.content_sha256 == "a" * 64

    def test_no_revision_evidence_is_none(self, db_manager: DatabaseManager):
        _seed_article(db_manager, content_hash=None)

        identity = resolve_report_identity(
            "https://noticiencias.com/posts/example", db_manager
        )

        assert identity.status == "resolved"
        assert identity.content_sha256 is None

    def test_attempt_from_another_article_is_ignored(self, db_manager: DatabaseManager):
        article_id = _seed_article(db_manager, content_hash="e" * 64)
        other_id = _seed_article(
            db_manager,
            url="https://example.com/other",
            published_url="https://noticiencias.com/posts/other",
        )
        _seed_attempt(
            db_manager,
            other_id,
            attempt_number=9,
            details=_fingerprint_details("9" * 64),
        )

        identity = resolve_report_identity(
            "https://noticiencias.com/posts/example", db_manager
        )

        assert identity.refinery_id == str(article_id)
        assert identity.content_sha256 == "e" * 64


def test_resolution_is_read_only(db_manager: DatabaseManager):
    article_id = _seed_article(db_manager, content_hash="c" * 64)
    _seed_attempt(
        db_manager,
        article_id,
        attempt_number=1,
        details=_fingerprint_details("a" * 64),
    )

    with db_manager.SessionLocal() as session:
        before = {
            "articles": session.execute(
                select(func.count()).select_from(Article)
            ).scalar_one(),
            "attempts": session.execute(
                select(func.count()).select_from(PublicationAttemptRecord)
            ).scalar_one(),
            "reports": session.execute(
                select(func.count()).select_from(ReaderReport)
            ).scalar_one(),
        }

    resolve_report_identity("https://noticiencias.com/posts/example", db_manager)
    resolve_report_identity("https://noticiencias.com/posts/missing", db_manager)

    with db_manager.SessionLocal() as session:
        after = {
            "articles": session.execute(
                select(func.count()).select_from(Article)
            ).scalar_one(),
            "attempts": session.execute(
                select(func.count()).select_from(PublicationAttemptRecord)
            ).scalar_one(),
            "reports": session.execute(
                select(func.count()).select_from(ReaderReport)
            ).scalar_one(),
        }

    assert after == before
