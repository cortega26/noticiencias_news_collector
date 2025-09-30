#!/usr/bin/env python3
"""
Migration: align article indexes with optimized dedupe and ranking pipeline (2025-09-30).
- Adds simhash_prefix bucket column.
- Drops redundant indexes.
- Creates covering/partial indexes for dedupe, category windows, and source stats.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv("NEWS_DB_PATH", ROOT / "data" / "news.db"))

SIMHASH_MASK = (1 << 64) - 1


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def drop_indexes(conn: sqlite3.Connection, names: Iterable[str]) -> None:
    for name in names:
        conn.execute(f"DROP INDEX IF EXISTS {name}")


def create_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_articles_completed_category_score_date
            ON articles(category, processing_status, final_score, collected_date);

        CREATE INDEX IF NOT EXISTS idx_articles_status_date_source
            ON articles(processing_status, collected_date, source_id);

        CREATE INDEX IF NOT EXISTS idx_articles_cluster_recency
            ON articles(cluster_id, collected_date);

        CREATE INDEX IF NOT EXISTS idx_articles_simhash_prefix_collected
            ON articles(simhash_prefix, collected_date)
            WHERE simhash_prefix IS NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_articles_cleanup_low_score
            ON articles(collected_date)
            WHERE final_score < 0.3;
        """
    )


def ensure_simhash_prefix(conn: sqlite3.Connection) -> None:
    if not column_exists(conn, "articles", "simhash_prefix"):
        conn.execute("ALTER TABLE articles ADD COLUMN simhash_prefix INTEGER")
    rows = conn.execute(
        "SELECT id, simhash FROM articles WHERE simhash IS NOT NULL"
    ).fetchall()
    for article_id, simhash in rows:
        prefix = ((int(simhash) & SIMHASH_MASK) >> 48) & 0xFFFF
        conn.execute(
            "UPDATE articles SET simhash_prefix=? WHERE id=?", (prefix, article_id)
        )


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        ensure_simhash_prefix(conn)
        drop_indexes(
            conn,
            [
                "idx_source_date",
                "idx_category_score",
                "idx_cluster_id",
                "idx_articles_completed_source_status_date",
                "idx_articles_completed_category_score",
                "ix_articles_cluster_id",
                "idx_processing_status_date",
                "ix_articles_processing_status",
            ],
        )
        create_indexes(conn)
        conn.execute("PRAGMA optimize")

    print("✅ migration 20250930_optimize_indexes applied")


if __name__ == "__main__":
    main()
