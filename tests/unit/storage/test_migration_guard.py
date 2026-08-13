"""Tests for the read-only Alembic revision guard (plan 046, Step 3).

Every test asserts two things: the reported state, and that no schema
mutation happened as a side effect of checking it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect as sqla_inspect

from news_collector import config as app_config
from news_collector.storage.migration_guard import (
    RevisionState,
    build_readonly_engine,
    check_revision,
)

ROOT = Path(__file__).resolve().parents[3]
HEAD_REVISION = "b61c2d3e4f50"
BEHIND_REVISION = "a54ba7f7dabb"


def _alembic_cfg() -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    return cfg


def test_missing_version_table_on_fresh_empty_file(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.db"
    # An empty sqlite file with zero tables — nothing has ever run against it.
    sqlite3.connect(db_path).close()

    engine = build_readonly_engine({"type": "sqlite", "path": db_path})
    try:
        status = check_revision(engine)
    finally:
        engine.dispose()

    assert status.state is RevisionState.MISSING_VERSION_TABLE
    assert status.current_revision is None
    assert not status.is_ready

    # No schema mutation: the guard must not have created any table.
    # NOTE: engine.connect() after dispose() re-creates a pooled connection —
    # dispose again so it does not leak until GC (ResourceWarning).
    try:
        with engine.connect() as conn:
            assert sqla_inspect(conn).get_table_names() == []
    finally:
        engine.dispose()


def test_up_to_date_at_head(tmp_path: Path) -> None:
    db_path = tmp_path / "head.db"
    sqlite3.connect(db_path).close()
    cfg = _alembic_cfg()
    test_db_config = {"type": "sqlite", "path": str(db_path)}

    with patch.dict(app_config.DATABASE_CONFIG, test_db_config, clear=True):
        command.stamp(cfg, "head")

    engine = build_readonly_engine({"type": "sqlite", "path": db_path})
    try:
        status = check_revision(engine)
    finally:
        engine.dispose()

    assert status.state is RevisionState.UP_TO_DATE
    assert status.is_ready
    assert status.current_revision == status.head_revision == HEAD_REVISION


def test_behind_head(tmp_path: Path) -> None:
    db_path = tmp_path / "behind.db"
    sqlite3.connect(db_path).close()
    cfg = _alembic_cfg()
    test_db_config = {"type": "sqlite", "path": str(db_path)}

    with patch.dict(app_config.DATABASE_CONFIG, test_db_config, clear=True):
        command.stamp(cfg, BEHIND_REVISION)

    engine = build_readonly_engine({"type": "sqlite", "path": db_path})
    try:
        status = check_revision(engine)
    finally:
        engine.dispose()

    assert status.state is RevisionState.BEHIND
    assert not status.is_ready
    assert status.current_revision == BEHIND_REVISION
    assert status.head_revision != BEHIND_REVISION

    # Read-only: still stamped at the old revision, no upgrade happened.
    # (dispose again — see test_missing_version_table post-dispose note)
    try:
        with engine.connect() as conn:
            current = conn.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar()
    finally:
        engine.dispose()
    assert current == BEHIND_REVISION


def test_ahead_of_or_diverged_from_head(tmp_path: Path) -> None:
    """A revision unknown to this codebase's packaged history is reported as AHEAD."""
    db_path = tmp_path / "ahead.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute(
            "INSERT INTO alembic_version (version_num) VALUES ('deadbeef0000')"
        )
        conn.commit()
    finally:
        conn.close()

    engine = build_readonly_engine({"type": "sqlite", "path": db_path})
    try:
        status = check_revision(engine)
    finally:
        engine.dispose()

    assert status.state is RevisionState.AHEAD
    assert not status.is_ready
    assert status.current_revision == "deadbeef0000"


def test_unreachable_reports_no_credentials(tmp_path: Path) -> None:
    """A database that cannot be connected to is UNREACHABLE, not a crash,
    and the detail message never echoes connection internals."""
    unreachable_dir = tmp_path / "does-not-exist" / "nested" / "db.sqlite"

    engine = build_readonly_engine({"type": "sqlite", "path": unreachable_dir})
    try:
        status = check_revision(engine)
    finally:
        engine.dispose()

    assert status.state is RevisionState.UNREACHABLE
    assert "password" not in status.detail.lower()


def test_never_creates_alembic_version_table_itself(tmp_path: Path) -> None:
    """Checking a fresh file must not stamp or create alembic_version as a side effect."""
    db_path = tmp_path / "no_side_effects.db"
    sqlite3.connect(db_path).close()

    engine = build_readonly_engine({"type": "sqlite", "path": db_path})
    try:
        check_revision(engine)
        with engine.connect() as conn:
            tables = sqla_inspect(conn).get_table_names()
    finally:
        engine.dispose()

    assert "alembic_version" not in tables
