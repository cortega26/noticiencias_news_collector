import contextlib
import copy
import json
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional

from news_collector.infrastructure.run_context import run_context
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)

# Aggregate-row column defaults, used both to create a fresh row for a
# source_id never seen before and as the schema for every write. Kept as a
# plain dict (not the DB row) so aggregate math can be replayed in memory
# without touching SQLite — see _apply_attempt/_apply_success/_apply_cost.
_FRESH_AGGREGATE_ROW: Dict[str, Any] = {
    "total_discovered": 0,
    "total_enrichment_attempted": 0,
    "total_publishable": 0,
    "http_success": 0,
    "http_attempts": 0,
    "plain_http_success": 0,
    "plain_http_attempts": 0,
    "scrapling_http_success": 0,
    "scrapling_http_attempts": 0,
    "headless_success": 0,
    "headless_attempts": 0,
    "scrapling_stealth_success": 0,
    "scrapling_stealth_attempts": 0,
    "proxy_success": 0,
    "proxy_attempts": 0,
    "scholarly_success": 0,
    "scholarly_attempts": 0,
    "avg_content_length": 0.0,
    "avg_enrichment_time": 0.0,
    "proxy_requests_used": 0,
    "headless_seconds_used": 0.0,
}

# Fixed, literal lookup tables — never built from the caller-supplied
# `strategy` string — so a value like "http_attempts = 999" (see
# test_record_attempt_ignores_untrusted_strategy_text) can never become a
# column name or SQL fragment.
_BUCKET_ATTEMPT_COLUMN = {
    "http": "http_attempts",
    "headless": "headless_attempts",
    "proxy": "proxy_attempts",
    "scholarly": "scholarly_attempts",
}
_BUCKET_SUCCESS_COLUMN = {
    "http": "http_success",
    "headless": "headless_success",
    "proxy": "proxy_success",
    "scholarly": "scholarly_success",
}
_RAW_ATTEMPT_COLUMN = {
    "http": "plain_http_attempts",
    "scrapling_http": "scrapling_http_attempts",
    "scrapling_stealth": "scrapling_stealth_attempts",
}
_RAW_SUCCESS_COLUMN = {
    "http": "plain_http_success",
    "scrapling_http": "scrapling_http_success",
    "scrapling_stealth": "scrapling_stealth_success",
}


def _normalize_strategy_bucket(strategy: Optional[str]) -> Optional[str]:
    """Maps concrete enrichment strategies to the aggregate metric bucket they
    should increment. History rows keep the original strategy string."""
    if strategy is None:
        return None

    strategy_buckets = {
        "http": "http",
        "scrapling_http": "http",
        "headless": "headless",
        "headless_fallback": "headless",
        "scrapling_stealth": "headless",
        "proxy": "proxy",
        "scholarly": "scholarly",
    }
    return strategy_buckets.get(strategy)


def _apply_attempt(row: Dict[str, Any], strategy: Optional[str]) -> Dict[str, Any]:
    """Pure: returns a new row reflecting one more attempt. Never mutates `row`."""
    row = dict(row)
    row["total_discovered"] += 1
    row["total_enrichment_attempted"] += 1

    bucket = _normalize_strategy_bucket(strategy)
    if bucket in _BUCKET_ATTEMPT_COLUMN:
        col = _BUCKET_ATTEMPT_COLUMN[bucket]
        row[col] += 1

    if strategy in _RAW_ATTEMPT_COLUMN:
        col = _RAW_ATTEMPT_COLUMN[strategy]
        row[col] += 1

    return row


def _apply_success(
    row: Dict[str, Any],
    strategy: str,
    duration: float,
    content_length: int,
    is_publishable: bool,
) -> Optional[Dict[str, Any]]:
    """Pure: returns a new row reflecting one more success, or None if
    `strategy` doesn't map to a known bucket (caller logs + skips, matching
    the previous early-return-with-warning behavior).

    avg_enrichment_time/avg_content_length are divided by
    total_enrichment_attempted (the attempt count), not by the success
    count — replicating the original per-event SQL exactly, including its
    path-dependence: a source with attempts that never got a matching
    success (failures) has a *smaller* effective divisor increase per
    success than "sum(durations)/count(successes)" would produce. This
    function must be applied once per event, in original event order, per
    source — never coalesced into a single sum/count operation, or the
    result silently diverges from history (see plans/038/spec.md for the
    worked counter-example that motivated this).
    """
    bucket = _normalize_strategy_bucket(strategy)
    if bucket is None:
        return None

    row = dict(row)

    if row["total_enrichment_attempted"] == 0:
        # Mirrors the original _execute_success_insert edge case: a success
        # arrived with no preceding attempt recorded for this source. Only
        # record_attempt/record_success ever create a row (record_cost's
        # UPDATE is a no-op against a missing source_id), so an *existing*
        # row can never legitimately have total_enrichment_attempted == 0 —
        # this branch is only reachable for a source seen for the first time.
        row["total_discovered"] = 1
        row["total_enrichment_attempted"] = 1

    total_attempts = row["total_enrichment_attempted"]
    if total_attempts > 1:
        new_avg_time = (
            (row["avg_enrichment_time"] * (total_attempts - 1)) + duration
        ) / total_attempts
        new_avg_len = (
            (row["avg_content_length"] * (total_attempts - 1)) + content_length
        ) / total_attempts
    else:
        new_avg_time = duration
        new_avg_len = content_length

    row["avg_enrichment_time"] = new_avg_time
    row["avg_content_length"] = new_avg_len
    row[_BUCKET_SUCCESS_COLUMN[bucket]] += 1
    row["total_publishable"] += 1 if is_publishable else 0

    if strategy in _RAW_SUCCESS_COLUMN:
        col = _RAW_SUCCESS_COLUMN[strategy]
        row[col] += 1

    return row


def _apply_cost(
    row: Dict[str, Any], proxy_requests: int, headless_seconds: float
) -> Dict[str, Any]:
    """Pure: returns a new row with cost counters incremented."""
    row = dict(row)
    row["proxy_requests_used"] += proxy_requests
    row["headless_seconds_used"] += headless_seconds
    return row


class EnrichmentMetricsStore:
    _instance: Optional["EnrichmentMetricsStore"] = None
    _lock = threading.RLock()
    _initialized: bool

    # DB Path is now instance-specific based on environment, but we still use singleton pattern
    # effectively per-process.

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(EnrichmentMetricsStore, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        environment: Optional[str] = None,
        db_path: Optional[str] = None,
        flush_batch_size: int = 1,
    ):
        if self._initialized:
            return

        with self._lock:
            if self._initialized:
                return
            self._init_db(environment=environment, db_path=db_path)
            self._buffer: List[Dict[str, Any]] = []
            self._flush_batch_size = max(1, flush_batch_size)
            self.flush_count = 0
            self._initialized = True

    @classmethod
    def create_isolated(
        cls,
        environment: Optional[str] = None,
        db_path: Optional[str] = None,
        flush_batch_size: int = 1,
    ) -> "EnrichmentMetricsStore":
        """Build a genuinely separate instance, bypassing the process-wide
        singleton entirely — for tests (or any caller) that need real
        environment/connection isolation instead of the shared
        `enrichment_metrics` global.

        Unlike `EnrichmentMetricsStore()`, repeated calls never return the
        same object, and closing one instance never affects another.
        """
        instance = object.__new__(cls)
        instance._initialized = False
        instance._init_db(environment=environment, db_path=db_path)
        instance._buffer = []
        instance._flush_batch_size = max(1, flush_batch_size)
        instance.flush_count = 0
        instance._initialized = True
        return instance

    def _init_db(
        self, environment: Optional[str] = None, db_path: Optional[str] = None
    ):
        env = environment or run_context.get_context().get("environment", "development")
        self.db_path = db_path or f"data/metrics/{env}/enrichment_metrics.db"

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
            plain_http_success INTEGER DEFAULT 0,
            plain_http_attempts INTEGER DEFAULT 0,
            scrapling_http_success INTEGER DEFAULT 0,
            scrapling_http_attempts INTEGER DEFAULT 0,
            headless_success INTEGER DEFAULT 0,
            headless_attempts INTEGER DEFAULT 0,
            scrapling_stealth_success INTEGER DEFAULT 0,
            scrapling_stealth_attempts INTEGER DEFAULT 0,
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
                    "ALTER TABLE enrichment_metrics ADD COLUMN plain_http_attempts INTEGER DEFAULT 0"
                )

            with contextlib.suppress(sqlite3.OperationalError):
                cur.execute(
                    "ALTER TABLE enrichment_metrics ADD COLUMN plain_http_success INTEGER DEFAULT 0"
                )

            with contextlib.suppress(sqlite3.OperationalError):
                cur.execute(
                    "ALTER TABLE enrichment_metrics ADD COLUMN scrapling_http_attempts INTEGER DEFAULT 0"
                )

            with contextlib.suppress(sqlite3.OperationalError):
                cur.execute(
                    "ALTER TABLE enrichment_metrics ADD COLUMN scrapling_http_success INTEGER DEFAULT 0"
                )

            with contextlib.suppress(sqlite3.OperationalError):
                cur.execute(
                    "ALTER TABLE enrichment_metrics ADD COLUMN scrapling_stealth_attempts INTEGER DEFAULT 0"
                )

            with contextlib.suppress(sqlite3.OperationalError):
                cur.execute(
                    "ALTER TABLE enrichment_metrics ADD COLUMN scrapling_stealth_success INTEGER DEFAULT 0"
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

    # ------------------------------------------------------------------
    # Batching control
    # ------------------------------------------------------------------

    def configure_batching(self, flush_batch_size: int) -> None:
        """Set how many buffered events accumulate before an automatic flush.

        1 (the default) reproduces the pre-plan-038 behavior exactly: every
        record_*() call commits immediately. Only raise this for a caller
        that can guarantee a matching flush() at its own completion — see
        `batched()`.
        """
        with self._lock:
            self._flush_batch_size = max(1, flush_batch_size)

    @contextlib.contextmanager
    def batched(self, flush_batch_size: int):
        """Temporarily raise the flush batch size, guaranteeing a flush (and
        restore to 1) on exit — including on exception. This is the only
        supported way to enable real batching: the STOP condition in plan
        038 ("stop if buffering can lose events on the supported process
        termination model") means batching must never be left enabled
        without a caller-guaranteed flush point.
        """
        previous = self._flush_batch_size
        self.configure_batching(flush_batch_size)
        try:
            yield self
        finally:
            self.flush()
            self.configure_batching(previous)

    def _maybe_flush(self) -> None:
        if len(self._buffer) >= self._flush_batch_size:
            self.flush()

    def flush(self) -> None:
        """Apply every buffered event to the database in one transaction.

        Groups events by source_id (preserving each source's own event
        order), seeds each source's in-memory row from its current DB state
        (or fresh defaults), replays events one at a time through the pure
        _apply_* functions, then writes one final upsert per touched source
        plus one history row per event — all in a single commit.

        On failure: rolls back (nothing partial is ever committed) and
        leaves the buffer untouched, so a caller can retry flush() later.
        Never silently discards buffered events.
        """
        with self._lock:
            if not self._buffer:
                return

            events = self._buffer

            by_source: Dict[str, List[Dict[str, Any]]] = {}
            for event in events:
                by_source.setdefault(event["source_id"], []).append(event)

            cur = self.conn.cursor()
            try:
                final_rows: Dict[str, Dict[str, Any]] = {}
                for source_id, source_events in by_source.items():
                    row = self._fetch_row(cur, source_id)
                    if row is None:
                        row = copy.deepcopy(_FRESH_AGGREGATE_ROW)
                    final_rows[source_id] = self._replay_events(row, source_events)

                for source_id, row in final_rows.items():
                    self._upsert_row(cur, source_id, row)

                # record_cost never wrote a history row in the original
                # implementation (only the aggregate UPDATE) — preserve that.
                history_rows = [
                    self._history_tuple(event)
                    for event in events
                    if event["type"] != "cost"
                ]
                cur.executemany(
                    """
                    INSERT INTO enrichment_history
                        (run_id, environment, source_id, event_type, strategy,
                         duration, content_length, is_publishable, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    history_rows,
                )

                self.conn.commit()
                self.flush_count += 1
            except Exception:
                self.conn.rollback()
                raise
            finally:
                cur.close()

            # Only clear the buffer once the transaction has committed
            # successfully — on failure the buffer (and any events that
            # arrived after the flush attempt began) survives for retry.
            del self._buffer[: len(events)]

    @staticmethod
    def _replay_events(
        row: Dict[str, Any], events: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Fold one source's buffered events into its aggregate row, in
        order. See _apply_success's docstring for why order matters."""
        for event in events:
            if event["type"] == "attempt":
                row = _apply_attempt(row, event["strategy"])
            elif event["type"] == "success":
                updated = _apply_success(
                    row,
                    event["strategy"],
                    event["duration"],
                    event["content_length"],
                    event["is_publishable"],
                )
                if updated is None:
                    logger.warning(f"Invalid strategy recorded: {event['strategy']}")
                    continue
                row = updated
            elif event["type"] == "cost":
                row = _apply_cost(
                    row, event["proxy_requests"], event["headless_seconds"]
                )
            # 'failure' events touch history only, not the aggregate row.
        return row

    @staticmethod
    def _history_tuple(event: Dict[str, Any]) -> tuple:
        """Build one enrichment_history row, matching exactly which columns
        the original per-event-type INSERT statements populated (the rest
        stay NULL via the table's column defaults)."""
        event_type = event["type"]
        if event_type == "attempt":
            duration = None
            content_length = None
            is_publishable = None
        elif event_type == "success":
            duration = event["duration"]
            content_length = event["content_length"]
            is_publishable = 1 if event["is_publishable"] else 0
        elif event_type == "failure":
            duration = event["duration"]
            content_length = None
            is_publishable = None
        else:
            raise ValueError(f"Unexpected history event type: {event_type!r}")

        return (
            event["run_id"],
            event["environment"],
            event["source_id"],
            event_type,
            event.get("strategy"),
            duration,
            content_length,
            is_publishable,
            event["metadata_json"],
        )

    def _fetch_row(
        self, cur: sqlite3.Cursor, source_id: str
    ) -> Optional[Dict[str, Any]]:
        cur.execute(
            "SELECT * FROM enrichment_metrics WHERE source_id = ?", (source_id,)
        )
        result = cur.fetchone()
        if result is None:
            return None
        cols = [description[0] for description in cur.description]
        row = dict(zip(cols, result, strict=False))
        row.pop("source_id", None)
        row.pop("last_updated", None)
        return row

    # Fixed, literal column list — the same one _FRESH_AGGREGATE_ROW.keys()
    # would produce, but spelled out so this is an ordinary hardcoded SQL
    # statement rather than one composed from a runtime column list.
    _UPSERT_SQL = """
        INSERT INTO enrichment_metrics (
            source_id, total_discovered, total_enrichment_attempted,
            total_publishable, http_success, http_attempts,
            plain_http_success, plain_http_attempts, scrapling_http_success,
            scrapling_http_attempts, headless_success, headless_attempts,
            scrapling_stealth_success, scrapling_stealth_attempts,
            proxy_success, proxy_attempts, scholarly_success,
            scholarly_attempts, avg_content_length, avg_enrichment_time,
            proxy_requests_used, headless_seconds_used, last_updated
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(source_id) DO UPDATE SET
            total_discovered = excluded.total_discovered,
            total_enrichment_attempted = excluded.total_enrichment_attempted,
            total_publishable = excluded.total_publishable,
            http_success = excluded.http_success,
            http_attempts = excluded.http_attempts,
            plain_http_success = excluded.plain_http_success,
            plain_http_attempts = excluded.plain_http_attempts,
            scrapling_http_success = excluded.scrapling_http_success,
            scrapling_http_attempts = excluded.scrapling_http_attempts,
            headless_success = excluded.headless_success,
            headless_attempts = excluded.headless_attempts,
            scrapling_stealth_success = excluded.scrapling_stealth_success,
            scrapling_stealth_attempts = excluded.scrapling_stealth_attempts,
            proxy_success = excluded.proxy_success,
            proxy_attempts = excluded.proxy_attempts,
            scholarly_success = excluded.scholarly_success,
            scholarly_attempts = excluded.scholarly_attempts,
            avg_content_length = excluded.avg_content_length,
            avg_enrichment_time = excluded.avg_enrichment_time,
            proxy_requests_used = excluded.proxy_requests_used,
            headless_seconds_used = excluded.headless_seconds_used,
            last_updated = CURRENT_TIMESTAMP
    """

    def _upsert_row(
        self, cur: sqlite3.Cursor, source_id: str, row: Dict[str, Any]
    ) -> None:
        cur.execute(
            self._UPSERT_SQL,
            (source_id, *(row[col] for col in _FRESH_AGGREGATE_ROW)),
        )

    # ------------------------------------------------------------------
    # Public recording API — unchanged signatures, now buffer-backed
    # ------------------------------------------------------------------

    def record_attempt(self, source_id: str, strategy: Optional[str] = None):
        """Records attempt in both aggregate and history tables."""
        ctx = run_context.get_context()
        with self._lock:
            self._buffer.append(
                {
                    "type": "attempt",
                    "source_id": source_id,
                    "strategy": strategy,
                    "run_id": ctx["run_id"],
                    "environment": ctx["environment"],
                    "metadata_json": json.dumps(ctx),
                }
            )
            self._maybe_flush()

    def record_success(
        self,
        source_id: str,
        strategy: str,
        duration: float,
        content_length: int,
        is_publishable: bool,
    ):
        ctx = run_context.get_context()
        with self._lock:
            self._buffer.append(
                {
                    "type": "success",
                    "source_id": source_id,
                    "strategy": strategy,
                    "duration": duration,
                    "content_length": content_length,
                    "is_publishable": is_publishable,
                    "run_id": ctx["run_id"],
                    "environment": ctx["environment"],
                    "metadata_json": json.dumps(ctx),
                }
            )
            self._maybe_flush()

    def record_failure(
        self, source_id: str, strategy: str, reason: str, duration: float = 0.0
    ):
        ctx = run_context.get_context()
        with self._lock:
            self._buffer.append(
                {
                    "type": "failure",
                    "source_id": source_id,
                    "strategy": strategy,
                    "duration": duration,
                    "run_id": ctx["run_id"],
                    "environment": ctx["environment"],
                    "metadata_json": json.dumps({"reason": reason, **ctx}),
                }
            )
            self._maybe_flush()

    def record_cost(
        self, source_id: str, proxy_requests: int = 0, headless_seconds: float = 0.0
    ):
        ctx = run_context.get_context()
        with self._lock:
            self._buffer.append(
                {
                    "type": "cost",
                    "source_id": source_id,
                    "proxy_requests": proxy_requests,
                    "headless_seconds": headless_seconds,
                    "run_id": ctx["run_id"],
                    "environment": ctx["environment"],
                    "metadata_json": json.dumps(ctx),
                }
            )
            self._maybe_flush()

    # ------------------------------------------------------------------
    # Reads — always flush first, so a caller reading through this same
    # instance never sees stale, buffered-but-uncommitted data.
    # ------------------------------------------------------------------

    def get_metrics(self, source_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self.flush()
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
            self.flush()
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
            self._buffer.clear()
            self.flush_count = 0
            cur = self.conn.cursor()
            cur.execute("DELETE FROM enrichment_metrics")
            cur.execute("DELETE FROM enrichment_history")
            self.conn.commit()
            cur.close()

    def close(self):
        """Closes the database connection."""
        with self._lock:
            if self._buffer:
                self.flush()
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
