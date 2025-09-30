"""20251005_dedupe_recency_indexes

- Deduplicates articles on content_hash before enforcing uniqueness.
- Replaces legacy dedupe and category indexes with recency-aware partial indexes.
- Adds a recency pool index to accelerate fallback clustering lookups.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv("NEWS_DB_PATH", ROOT / "data" / "news.db"))


def drop_indexes(conn: sqlite3.Connection, names: Iterable[str]) -> None:
    for name in names:
        conn.execute(f"DROP INDEX IF EXISTS {name}")


def remove_content_hash_duplicates(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        DELETE FROM articles
        WHERE content_hash IS NOT NULL
          AND rowid NOT IN (
            SELECT MIN(rowid)
            FROM articles
            WHERE content_hash IS NOT NULL
            GROUP BY content_hash
          );
        """
    )


def create_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_articles_content_hash
            ON articles(content_hash);

        CREATE INDEX IF NOT EXISTS idx_articles_completed_category_score_recent
            ON articles(category, final_score, collected_date)
            WHERE processing_status = 'completed';

        CREATE INDEX IF NOT EXISTS idx_articles_cluster_recent_notnull
            ON articles(cluster_id, collected_date)
            WHERE cluster_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_articles_simhash_prefix_recent
            ON articles(simhash_prefix, collected_date)
            WHERE simhash_prefix IS NOT NULL AND simhash IS NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_articles_recent_dedupe_pool
            ON articles(collected_date)
            WHERE simhash IS NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_articles_status_date_source
            ON articles(processing_status, collected_date, source_id);

        CREATE INDEX IF NOT EXISTS idx_articles_cleanup_low_score
            ON articles(collected_date)
            WHERE final_score < 0.3;
        """
    )


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        remove_content_hash_duplicates(conn)
        drop_indexes(
            conn,
            [
                "ix_articles_content_hash",
                "idx_articles_simhash_prefix_collected",
                "idx_articles_completed_category_score_date",
                "idx_articles_cluster_recency",
                "idx_articles_recent_dedupe_pool",
                "idx_articles_completed_category_score_recent",
                "idx_articles_cluster_recent_notnull",
                "idx_articles_simhash_prefix_recent",
            ],
        )
        create_indexes(conn)
        conn.execute("PRAGMA optimize")

    print("✅ migration 20251005_dedupe_recency_indexes applied")


if __name__ == "__main__":
    main()
