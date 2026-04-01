import contextlib
import json
import os
import sqlite3
import threading
from typing import Any, Dict, Optional

from news_collector.infrastructure.run_context import run_context
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)


class EnrichmentMetricsStore:
    _instance = None
    _lock = threading.RLock()

    # DB Path is now instance-specific based on environment, but we still use singleton pattern
    # effectively per-process.

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(EnrichmentMetricsStore, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        with self._lock:
            if self._initialized:
                return
            self._init_db()
            self._initialized = True

    def _init_db(self):
        # Determine Path based on Environment
        env = run_context.get_context().get("environment", "development")
        self.db_path = f"data/metrics/{env}/enrichment_metrics.db"

        logger.info(f"Initializing Metrics Store for env='{env}' at '{self.db_path}'")

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._create_tables()

    @property
    def cursor(self):
        """Backward compatibility shim for older tests expecting a direct cursor."""
        return self.conn.cursor()

    def _create_tables(self):
        # 1. Aggregates Table (Existing)
        query_metrics = """
        CREATE TABLE IF NOT EXISTS enrichment_metrics (
            source_id TEXT PRIMARY KEY,
            total_discovered INTEGER DEFAULT 0,
            total_enrichment_attempted INTEGER DEFAULT 0,
            total_publishable INTEGER DEFAULT 0,
            http_success INTEGER DEFAULT 0,
            http_attempts INTEGER DEFAULT 0,
            headless_success INTEGER DEFAULT 0,
            headless_attempts INTEGER DEFAULT 0,
            proxy_success INTEGER DEFAULT 0,
            proxy_attempts INTEGER DEFAULT 0,
            scholarly_success INTEGER DEFAULT 0,
            scholarly_attempts INTEGER DEFAULT 0,
            avg_content_length REAL DEFAULT 0.0,
            avg_enrichment_time REAL DEFAULT 0.0,
            proxy_requests_used INTEGER DEFAULT 0,
            headless_seconds_used REAL DEFAULT 0.0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """

        # 2. Run History Table (New - For Attribution)
        query_history = """
        CREATE TABLE IF NOT EXISTS enrichment_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            environment TEXT NOT NULL,
            source_id TEXT NOT NULL,
            event_type TEXT NOT NULL, -- 'attempt', 'success', 'failure'
            strategy TEXT,
            duration REAL,
            content_length INTEGER,
            is_publishable BOOLEAN,
            metadata JSON
        )
        """

        with self._lock:
            cur = self.conn.cursor()
            cur.execute(query_metrics)
            cur.execute(query_history)

            # Migrations for Aggregates (Idempotent)
            with contextlib.suppress(sqlite3.OperationalError):
                cur.execute(
                    "ALTER TABLE enrichment_metrics ADD COLUMN http_attempts INTEGER DEFAULT 0"
                )

            with contextlib.suppress(sqlite3.OperationalError):
                cur.execute(
                    "ALTER TABLE enrichment_metrics ADD COLUMN headless_attempts INTEGER DEFAULT 0"
                )

            with contextlib.suppress(sqlite3.OperationalError):
                cur.execute(
                    "ALTER TABLE enrichment_metrics ADD COLUMN proxy_attempts INTEGER DEFAULT 0"
                )

            with contextlib.suppress(sqlite3.OperationalError):
                cur.execute(
                    "ALTER TABLE enrichment_metrics ADD COLUMN scholarly_attempts INTEGER DEFAULT 0"
                )

            self.conn.commit()
            cur.close()

    def record_attempt(self, source_id: str, strategy: Optional[str] = None):
        """Records attempt in both aggregate and history tables."""
        ctx = run_context.get_context()

        with self._lock:
            cur = self.conn.cursor()
            # Use fixed SQL statements per strategy to avoid runtime SQL composition.
            if strategy == "http":
                cur.execute(
                    """
                    INSERT INTO enrichment_metrics (source_id, total_discovered, total_enrichment_attempted, http_attempts)
                    VALUES (?, 1, 1, 1)
                    ON CONFLICT(source_id) DO UPDATE SET
                    total_discovered = total_discovered + 1,
                    total_enrichment_attempted = total_enrichment_attempted + 1,
                    http_attempts = http_attempts + 1,
                    last_updated = CURRENT_TIMESTAMP
                """,
                    (source_id,),
                )
            elif strategy == "headless":
                cur.execute(
                    """
                    INSERT INTO enrichment_metrics (source_id, total_discovered, total_enrichment_attempted, headless_attempts)
                    VALUES (?, 1, 1, 1)
                    ON CONFLICT(source_id) DO UPDATE SET
                    total_discovered = total_discovered + 1,
                    total_enrichment_attempted = total_enrichment_attempted + 1,
                    headless_attempts = headless_attempts + 1,
                    last_updated = CURRENT_TIMESTAMP
                """,
                    (source_id,),
                )
            elif strategy == "proxy":
                cur.execute(
                    """
                    INSERT INTO enrichment_metrics (source_id, total_discovered, total_enrichment_attempted, proxy_attempts)
                    VALUES (?, 1, 1, 1)
                    ON CONFLICT(source_id) DO UPDATE SET
                    total_discovered = total_discovered + 1,
                    total_enrichment_attempted = total_enrichment_attempted + 1,
                    proxy_attempts = proxy_attempts + 1,
                    last_updated = CURRENT_TIMESTAMP
                """,
                    (source_id,),
                )
            elif strategy == "scholarly":
                cur.execute(
                    """
                    INSERT INTO enrichment_metrics (source_id, total_discovered, total_enrichment_attempted, scholarly_attempts)
                    VALUES (?, 1, 1, 1)
                    ON CONFLICT(source_id) DO UPDATE SET
                    total_discovered = total_discovered + 1,
                    total_enrichment_attempted = total_enrichment_attempted + 1,
                    scholarly_attempts = scholarly_attempts + 1,
                    last_updated = CURRENT_TIMESTAMP
                """,
                    (source_id,),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO enrichment_metrics (source_id, total_discovered, total_enrichment_attempted)
                    VALUES (?, 1, 1)
                    ON CONFLICT(source_id) DO UPDATE SET
                    total_discovered = total_discovered + 1,
                    total_enrichment_attempted = total_enrichment_attempted + 1,
                    last_updated = CURRENT_TIMESTAMP
                """,
                    (source_id,),
                )

            # Insert History
            cur.execute(
                """
                INSERT INTO enrichment_history (run_id, environment, source_id, event_type, strategy, metadata)
                VALUES (?, ?, ?, 'attempt', ?, ?)
            """,
                (
                    ctx["run_id"],
                    ctx["environment"],
                    source_id,
                    strategy,
                    json.dumps(ctx),
                ),
            )

            self.conn.commit()
            cur.close()

    def record_success(
        self,
        source_id: str,
        strategy: str,
        duration: float,
        content_length: int,
        is_publishable: bool,
    ):
        ctx = run_context.get_context()
        valid_strategies = ["http", "headless", "proxy", "scholarly"]

        if strategy not in valid_strategies:
            logger.warning(f"Invalid strategy recorded: {strategy}")
            return

        with self._lock:
            cur = self.conn.cursor()
            # Update Aggregates (Existing Logic)
            cur.execute(
                "SELECT total_enrichment_attempted, avg_enrichment_time, avg_content_length FROM enrichment_metrics WHERE source_id = ?",
                (source_id,),
            )
            row = cur.fetchone()

            if row:
                total_attempts = row[0]
                old_avg_time = row[1]
                old_avg_len = row[2]

                # Careful with averaging logic - sticking to moving average approximation or simpler accumulation?
                # The existing logic tries to recompute average.
                # total_attempts was already incremented in record_attempt.

                if total_attempts > 1:
                    new_avg_time = (
                        (old_avg_time * (total_attempts - 1)) + duration
                    ) / total_attempts
                    new_avg_len = (
                        (old_avg_len * (total_attempts - 1)) + content_length
                    ) / total_attempts
                else:
                    new_avg_time = duration
                    new_avg_len = content_length

                self._execute_success_update(
                    cur=cur,
                    strategy=strategy,
                    source_id=source_id,
                    publishable_increment=1 if is_publishable else 0,
                    new_avg_len=new_avg_len,
                    new_avg_time=new_avg_time,
                )
            else:
                # Should have been created by record_attempt, but handle edge case
                self._execute_success_insert(
                    cur=cur,
                    strategy=strategy,
                    source_id=source_id,
                    publishable_increment=1 if is_publishable else 0,
                    content_length=content_length,
                    duration=duration,
                )

            # Insert History
            cur.execute(
                """
                INSERT INTO enrichment_history (run_id, environment, source_id, event_type, strategy, duration, content_length, is_publishable, metadata)
                VALUES (?, ?, ?, 'success', ?, ?, ?, ?, ?)
            """,
                (
                    ctx["run_id"],
                    ctx["environment"],
                    source_id,
                    strategy,
                    duration,
                    content_length,
                    1 if is_publishable else 0,
                    json.dumps(ctx),
                ),
            )

            self.conn.commit()
            cur.close()

    def _execute_success_update(
        self,
        cur: sqlite3.Cursor,
        strategy: str,
        source_id: str,
        publishable_increment: int,
        new_avg_len: float,
        new_avg_time: float,
    ) -> None:
        if strategy == "http":
            cur.execute(
                """
                UPDATE enrichment_metrics
                SET
                    http_success = http_success + 1,
                    total_publishable = total_publishable + ?,
                    avg_content_length = ?,
                    avg_enrichment_time = ?,
                    last_updated = CURRENT_TIMESTAMP
                WHERE source_id = ?
            """,
                (publishable_increment, new_avg_len, new_avg_time, source_id),
            )
        elif strategy == "headless":
            cur.execute(
                """
                UPDATE enrichment_metrics
                SET
                    headless_success = headless_success + 1,
                    total_publishable = total_publishable + ?,
                    avg_content_length = ?,
                    avg_enrichment_time = ?,
                    last_updated = CURRENT_TIMESTAMP
                WHERE source_id = ?
            """,
                (publishable_increment, new_avg_len, new_avg_time, source_id),
            )
        elif strategy == "proxy":
            cur.execute(
                """
                UPDATE enrichment_metrics
                SET
                    proxy_success = proxy_success + 1,
                    total_publishable = total_publishable + ?,
                    avg_content_length = ?,
                    avg_enrichment_time = ?,
                    last_updated = CURRENT_TIMESTAMP
                WHERE source_id = ?
            """,
                (publishable_increment, new_avg_len, new_avg_time, source_id),
            )
        elif strategy == "scholarly":
            cur.execute(
                """
                UPDATE enrichment_metrics
                SET
                    scholarly_success = scholarly_success + 1,
                    total_publishable = total_publishable + ?,
                    avg_content_length = ?,
                    avg_enrichment_time = ?,
                    last_updated = CURRENT_TIMESTAMP
                WHERE source_id = ?
            """,
                (publishable_increment, new_avg_len, new_avg_time, source_id),
            )

    def _execute_success_insert(
        self,
        cur: sqlite3.Cursor,
        strategy: str,
        source_id: str,
        publishable_increment: int,
        content_length: int,
        duration: float,
    ) -> None:
        if strategy == "http":
            cur.execute(
                """
                INSERT INTO enrichment_metrics (
                    source_id,
                    http_success,
                    total_publishable,
                    avg_content_length,
                    avg_enrichment_time,
                    total_discovered,
                    total_enrichment_attempted
                )
                VALUES (?, 1, ?, ?, ?, 1, 1)
            """,
                (source_id, publishable_increment, content_length, duration),
            )
        elif strategy == "headless":
            cur.execute(
                """
                INSERT INTO enrichment_metrics (
                    source_id,
                    headless_success,
                    total_publishable,
                    avg_content_length,
                    avg_enrichment_time,
                    total_discovered,
                    total_enrichment_attempted
                )
                VALUES (?, 1, ?, ?, ?, 1, 1)
            """,
                (source_id, publishable_increment, content_length, duration),
            )
        elif strategy == "proxy":
            cur.execute(
                """
                INSERT INTO enrichment_metrics (
                    source_id,
                    proxy_success,
                    total_publishable,
                    avg_content_length,
                    avg_enrichment_time,
                    total_discovered,
                    total_enrichment_attempted
                )
                VALUES (?, 1, ?, ?, ?, 1, 1)
            """,
                (source_id, publishable_increment, content_length, duration),
            )
        elif strategy == "scholarly":
            cur.execute(
                """
                INSERT INTO enrichment_metrics (
                    source_id,
                    scholarly_success,
                    total_publishable,
                    avg_content_length,
                    avg_enrichment_time,
                    total_discovered,
                    total_enrichment_attempted
                )
                VALUES (?, 1, ?, ?, ?, 1, 1)
            """,
                (source_id, publishable_increment, content_length, duration),
            )

    def record_failure(
        self, source_id: str, strategy: str, reason: str, duration: float = 0.0
    ):
        ctx = run_context.get_context()

        with self._lock:
            cur = self.conn.cursor()
            # Insert History
            cur.execute(
                """
                INSERT INTO enrichment_history (run_id, environment, source_id, event_type, strategy, duration, metadata)
                VALUES (?, ?, ?, 'failure', ?, ?, ?)
            """,
                (
                    ctx["run_id"],
                    ctx["environment"],
                    source_id,
                    strategy,
                    duration,
                    json.dumps({"reason": reason, **ctx}),
                ),
            )

            self.conn.commit()
            cur.close()

    def record_cost(
        self, source_id: str, proxy_requests: int = 0, headless_seconds: float = 0.0
    ):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                """
                UPDATE enrichment_metrics
                SET
                    proxy_requests_used = proxy_requests_used + ?,
                    headless_seconds_used = headless_seconds_used + ?,
                    last_updated = CURRENT_TIMESTAMP
                WHERE source_id = ?
            """,
                (proxy_requests, headless_seconds, source_id),
            )
            self.conn.commit()
            cur.close()

    def get_metrics(self, source_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            cur = self.conn.cursor()
            try:
                cur.execute(
                    "SELECT * FROM enrichment_metrics WHERE source_id = ?", (source_id,)
                )
                row = cur.fetchone()
                if row:
                    cols = [description[0] for description in cur.description]
                    return dict(zip(cols, row, strict=False))
                return None
            finally:
                cur.close()

    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            cur = self.conn.cursor()
            try:
                cur.execute("SELECT * FROM enrichment_metrics")
                rows = cur.fetchall()
                cols = [description[0] for description in cur.description]
                return {row[0]: dict(zip(cols, row, strict=False)) for row in rows}
            finally:
                cur.close()

    def reset(self):
        """For testing or fresh runs."""
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("DELETE FROM enrichment_metrics")
            cur.execute("DELETE FROM enrichment_history")
            self.conn.commit()
            cur.close()

    def close(self):
        """Closes the database connection."""
        with self._lock:
            if hasattr(self, "conn") and self.conn:
                self.conn.close()
                self.conn = None


# Global instance
enrichment_metrics = EnrichmentMetricsStore()


class ProductionReadonlyStore:
    """
    A read-only view of the PRODUCTION metrics database.
    Used by the StrategyOptimizer to ensure recommendations are based on real data,
    regardless of the current running environment (e.g. dry-run).
    """

    def __init__(self):
        # Force Production Path
        self.db_path = "data/metrics/production/enrichment_metrics.db"
        self.conn = None
        # Lazy connect on first access to handle cases where DB is created after init

    def _connect(self):
        if self.conn:
            return True
        if os.path.exists(self.db_path):
            try:
                self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
                # self.cursor removed
                logger.info(f"Connected to ProductionReadonlyStore at {self.db_path}")
                return True
            except Exception as e:
                logger.error(f"Failed to connect to production DB: {e}")
        return False

    def get_metrics(self, source_id: str) -> Optional[Dict[str, Any]]:
        if not self._connect():
            return None
        cur = self.conn.cursor()
        try:
            cur.execute(
                "SELECT * FROM enrichment_metrics WHERE source_id = ?", (source_id,)
            )
            row = cur.fetchone()
            if row:
                cols = [description[0] for description in cur.description]
                return dict(zip(cols, row, strict=False))
        except Exception as e:
            logger.error(f"Error reading prod metrics: {e}")
        finally:
            cur.close()
        return None

    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        if not self._connect():
            return {}
        cur = self.conn.cursor()
        try:
            cur.execute("SELECT * FROM enrichment_metrics")
            rows = cur.fetchall()
            cols = [description[0] for description in cur.description]
            return {row[0]: dict(zip(cols, row, strict=False)) for row in rows}
        except Exception:
            return {}
        finally:
            cur.close()

    def close(self):
        # Closes the production database connection.
        if hasattr(self, "conn") and self.conn:
            self.conn.close()
            self.conn = None


# Global instance for optimizer
production_metrics_view = ProductionReadonlyStore()
