"""Tests for automatic schema migrations applied by DatabaseManager."""

from __future__ import annotations

import sqlite3
import sys
import types
from pathlib import Path

import pytest
from sqlalchemy import inspect as sqla_inspect

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

if "src" not in sys.modules:
    stub = types.ModuleType("src")
    stub.__path__ = [str(SRC_DIR)]
    sys.modules["src"] = stub

from src.storage.database import DatabaseManager


def _create_legacy_sources_table(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
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
            """
        )
        conn.commit()


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

    inspector = sqla_inspect(manager.engine)
    columns = {col["name"] for col in inspector.get_columns("sources")}

    for column in missing_columns:
        assert column in columns, (
            f"Expected column '{column}' to be created via migration"
        )
