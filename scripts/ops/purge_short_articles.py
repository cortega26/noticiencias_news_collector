import sqlite3
from pathlib import Path

# Adjust path if needed
DB_PATH = Path("data/news_v3.db")
MIN_LENGTH = 750


def purge():
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH.absolute()}")
        # Try absolute path based on user info
        DB_PATH_ABS = Path("/home/cortega26/noticiencias_news_collector/data/news.db")
        if DB_PATH_ABS.exists():
            conn = sqlite3.connect(DB_PATH_ABS)
            print(f"Connected to {DB_PATH_ABS}")
        else:
            return
    else:
        conn = sqlite3.connect(DB_PATH)
        print(f"Connected to {DB_PATH}")

    cursor = conn.cursor()

    try:
        # Check count of short or empty articles
        # usage of COALESCE logic: length(content) will be null if content is null
        # usage of COALESCE logic: length(content) will be null if content is null
        query_count = f"SELECT count(*) FROM articles WHERE content IS NULL OR length(content) < {MIN_LENGTH}"  # noqa: S608 # nosec
        cursor.execute(query_count)
        count = cursor.fetchone()[0]

        if count == 0:
            print(f"No stale articles found (< {MIN_LENGTH} chars). Database is clean.")
        else:
            print(f"Found {count} stale articles (short or empty). Purging...")

            # Show IDs of some being deleted for audit
            cursor.execute(
                f"SELECT id, length(content) FROM articles WHERE content IS NULL OR length(content) < {MIN_LENGTH} LIMIT 5"  # noqa: S608 # nosec
            )
            for row in cursor.fetchall():
                print(f" - Deleting Article ID {row[0]} (Length: {row[1]})")

            query_delete = f"DELETE FROM articles WHERE content IS NULL OR length(content) < {MIN_LENGTH}"  # noqa: S608 # nosec
            cursor.execute(query_delete)
            conn.commit()
            print(f"Successfully purged {count} articles.")

    except Exception as e:
        print(f"Database error: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    purge()
