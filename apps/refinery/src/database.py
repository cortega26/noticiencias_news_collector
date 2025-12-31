import sqlite3
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize the database schema."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS processed_articles (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        filename TEXT UNIQUE NOT NULL,
                        processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        status TEXT DEFAULT 'success'
                    )
                """)
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Database initialization failed: {e}")
            raise

    def is_processed(self, filename: str) -> bool:
        """Check if a file has already been processed."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT 1 FROM processed_articles WHERE filename = ? AND status = 'success'", 
                    (filename,)
                )
                return cursor.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"Error checking status for {filename}: {e}")
            return False

    def mark_processed(self, filename: str, status: str = "success"):
        """Mark a file as processed."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO processed_articles (filename, processed_at, status)
                    VALUES (?, ?, ?)
                    """,
                    (filename, datetime.now(), status)
                )
                conn.commit()
                logger.info(f"Marked {filename} as {status} in database.")
        except sqlite3.Error as e:
            logger.error(f"Error marking {filename} as processed: {e}")
