import sqlite3

DB_PATH = "data/news_v3.db"
TARGETS = [
    "cell",
    "phys_org",
    "medicalxpress",
    "techxplore",
    "scitechdaily",
    "sciencedaily_top",
]


def reset_sources():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print(f"Resetting last_fetched_at for {len(TARGETS)} sources...")

    # In SQLite, it might be stored as string or whatever the schema is.
    # Usually 'sources' table? Or 'source_states'?
    # Checking schema would be good, but typically it is 'source_states' if using BaseCollector state management,
    # or just separate metadata table.
    # The BaseCollector uses `db_manager.get_source_state(source_id)`.
    # Let's try to list tables first to be sure, or just blindly update commonly named tables.

    # Check tables
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r[0] for r in cursor.fetchall()]
        print(f"Tables: {tables}")

        if "sources" in tables:
            for source in TARGETS:
                # Reset all state columns to force immediate retry
                cursor.execute(
                    """
                    UPDATE sources
                    SET last_checked = NULL,
                        next_retry_at = NULL,
                        status = 'ACTIVE',
                        consecutive_failures = 0,
                        error_message = NULL
                    WHERE id = ?
                    """,
                    (source,),
                )
                if cursor.rowcount > 0:
                    print(f"  - Reset {source}")
                else:
                    print(f"  - {source} not found in sources table")

    except Exception as e:
        print(f"Error: {e}")

    conn.commit()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    reset_sources()
