"""Plan 036 follow-up (subagent review finding).

A caught exception inside `ArticleRepository._session()` that returns
`False` without first rolling back leaves the session in SQLAlchemy's
"needs rollback" state. `DatabaseManager.get_session()` then
unconditionally calls `session.commit()` again on normal exit — which
raises `PendingRollbackError`, discarding the `return False` a caller
(e.g. `ScoringCoordinator._process_page`) relies on to treat a real
persistence failure as a resumable cycle failure rather than a crash.

Fixed by adding `session.rollback()` before every `return False` in
`article_repository.py`'s exception handlers
(`update_validation_status_bulk`, `update_articles_score_bulk`,
`update_article_score`, `delete_article`).
"""

import pytest
from sqlalchemy.exc import IntegrityError, PendingRollbackError

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article, Base


@pytest.fixture
def db_manager(tmp_path):
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "t.db"})
    Base.metadata.create_all(manager.engine)
    yield manager
    manager.close()


def _trigger_real_integrity_error(session):
    """A genuine UNIQUE-constraint violation — the same class of failure
    a bulk update could hit against a real, concurrently-modified database.
    SQLAlchemy must invalidate the session's transaction for this, unlike
    an ordinary Python exception."""
    session.add(
        Article(url="http://dup.example/1", title="A", source_id="s", source_name="S")
    )
    session.flush()
    session.add(
        Article(url="http://dup.example/1", title="B", source_id="s", source_name="S")
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_naive_return_without_rollback_lets_pendingrollback_escape(db_manager):
    """Characterizes the pre-fix bug: a bare `return` (no rollback) after a
    caught IntegrityError leaks a PendingRollbackError out of
    get_session()'s own trailing commit on normal exit."""
    with pytest.raises(PendingRollbackError):
        with db_manager.get_session() as session:
            _trigger_real_integrity_error(session)
            # No session.rollback() here — reproduces the pre-fix code path.


def test_rollback_before_return_lets_get_session_exit_cleanly(db_manager):
    """Proves the fix: rolling back before returning leaves the session
    clean, so get_session()'s trailing commit is a harmless no-op."""
    with db_manager.get_session() as session:
        _trigger_real_integrity_error(session)
        session.rollback()
    # No exception raised — get_session() exited normally.
