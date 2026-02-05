"""Tests for automatic schema migrations applied by DatabaseManager."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import inspect as sqla_inspect

ROOT = Path(__file__).resolve().parents[1]

from news_collector.storage.database import DatabaseManager
from unittest.mock import patch
from news_collector import config as app_config


def _create_legacy_sources_table(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                CREATE TABLE sources (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    credibility_score REAL NOT NULL,
                    category TEXT NOT NULL,
                    update_frequency TEXT,
                    last_checked TIMESTAMP,
                    last_successful_check TIMESTAMP,
                    last_article_found TIMESTAMP,
                    total_articles_collected INTEGER DEFAULT 0,
                    articles_this_month INTEGER DEFAULT 0,
                    average_articles_per_check REAL DEFAULT 0.0,
                    success_rate REAL DEFAULT 1.0,
                    duplicate_rate REAL DEFAULT 0.0,
                    average_article_score REAL,
                    is_active INTEGER DEFAULT 1,
                    consecutive_failures INTEGER DEFAULT 0,
                    error_message TEXT,
                    custom_config TEXT
                );
                """)
            conn.commit()
        finally:
            cursor.close()
    finally:
        conn.close()


@pytest.mark.parametrize(
    "missing_columns",
    [
        {
            "suppressed_until",
            "suppression_reason",
            "auto_suppressed",
            "dq_consecutive_anomalies",
            "last_canary_check",
            "last_canary_status",
        }
    ],
)
def test_database_manager_backfills_suppression_columns(
    tmp_path: Path, missing_columns: set[str]
) -> None:
    """The manager should auto-upgrade legacy source tables missing suppression fields."""

    db_path = tmp_path / "legacy.db"
    _create_legacy_sources_table(db_path)

    manager = DatabaseManager(database_config={"type": "sqlite", "path": db_path})
    try:
        # 1. Verify that DatabaseManager properly refuses to touch the schema
        with manager.engine.connect() as connection:
            inspector = sqla_inspect(connection)
            columns = {col["name"] for col in inspector.get_columns("sources")}

        # Check a sample column is MISSING initially
        assert "auto_suppressed" not in columns, "DatabaseManager should not auto-migrate anymore"

        # 2. Run Alembic Migration Programmatically
        from alembic import command
        from alembic.config import Config

        # Setup Alembic Config (point to alembic.ini in root)
        alembic_cfg = Config(str(ROOT / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
        # We must also patch the app config because env.py reads from it
        test_db_config = {"type": "sqlite", "path": str(db_path)}
        
        with patch.dict(app_config.DATABASE_CONFIG, test_db_config, clear=True):
             # Stamp it as valid legacy state first (optional but good for robustness)
             command.stamp(alembic_cfg, "cb486d1d980d") # Stamp as initial revision
        
             # Now run the smart migration
             command.upgrade(alembic_cfg, "head")

        # 3. Verify columns exist after migration
        with manager.engine.connect() as connection:
            inspector = sqla_inspect(connection)
            columns = {col["name"] for col in inspector.get_columns("sources")}

        for column in missing_columns:
            assert (
                column in columns
            ), f"Expected column '{column}' to be created via migration"
    finally:
        manager.close()


def test_database_manager_has_article_publication_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "articles.db"

    manager = DatabaseManager(database_config={"type": "sqlite", "path": db_path})
    try:
        with manager.engine.connect() as connection:
            inspector = sqla_inspect(connection)
            columns = {col["name"] for col in inspector.get_columns("articles")}

        assert "published_at" in columns
        assert "published_url" in columns
    finally:
        manager.close()


def test_database_manager_creates_content_hash_unique_index(tmp_path: Path) -> None:
    db_path = tmp_path / "articles_index.db"

    manager = DatabaseManager(database_config={"type": "sqlite", "path": db_path})
    try:
        with manager.engine.connect() as connection:
            inspector = sqla_inspect(connection)
            indexes = {idx["name"] for idx in inspector.get_indexes("articles")}

        assert "uq_articles_content_hash" in indexes
    finally:
        manager.close()
