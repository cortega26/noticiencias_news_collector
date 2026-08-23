"""Targeted unit tests for DatabaseManager/build_database_url gaps.

Plan 060 / Phase 3b: touching database.py (to expose `db.lifecycle`) pulls
it into this repo's coverage ratchet, which surfaced two pre-existing,
cheaply-coverable gaps unrelated to the lifecycle change itself:

- `build_database_url`'s PostgreSQL branch — a pure, side-effect-free
  function (per its own docstring) with no test anywhere despite being
  shared by DatabaseManager and the read-only migration guard.
- `DatabaseManager.close()`'s idempotency guard (calling close() when the
  engine is already None).

Both are covered here rather than via the deprecated `db.X()` delegate
surface (recon finding 2 explicitly says new code should stop relying on
that pattern, so adding smoke tests for the delegate one-liners would
just add weight to what's being phased out).
"""

import pytest

from news_collector.storage.database import DatabaseManager, build_database_url


def test_build_database_url_postgresql_without_sslmode():
    url = build_database_url(
        {
            "type": "postgresql",
            "user": "app",
            "password": "secret",
            "host": "db.example.com",
            "port": 5432,
            "name": "news",
        }
    )
    assert url.drivername == "postgresql"
    assert url.username == "app"
    assert url.host == "db.example.com"
    assert url.database == "news"
    assert "sslmode" not in url.query


def test_build_database_url_postgresql_with_sslmode():
    url = build_database_url(
        {
            "type": "postgresql",
            "user": "app",
            "password": "secret",
            "host": "db.example.com",
            "port": 5432,
            "name": "news",
            "sslmode": "require",
        }
    )
    assert url.query["sslmode"] == "require"


def test_build_database_url_unsupported_type_raises():
    with pytest.raises(ValueError):
        build_database_url({"type": "mongodb"})


def test_database_manager_close_is_idempotent(tmp_path):
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "idempotent.db"})
    manager.close()
    assert manager.engine is None
    # Second close: engine is already None — must not raise.
    manager.close()
    assert manager.engine is None
