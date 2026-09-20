"""Persistent LLM attempt metrics (SQLite) — the memory of the provider chain.

Every ``llm.attempt`` (see ``infrastructure.llm.attempts``) becomes one row so
later iterations can answer, with data rather than anecdotes: which provider
fails how (timeouts vs 5xx vs blank responses), how often each one is skipped
while degraded, latency percentiles, and who actually *saved* a call after
another provider failed.

Design constraints:
* fail-open — a metrics failure must never break or slow an LLM call (errors
  are counted and logged once, then swallowed);
* no shared connection — one short-lived connection per operation, WAL mode,
  so concurrent writers (scorers, editor, admin API) do not corrupt state;
* bounded — rows older than ``retention_days`` are purged when the store opens.
"""

from __future__ import annotations

import contextlib
import math
import os
import sqlite3
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from news_collector.infrastructure.llm.attempts import (
    AttemptRecord,
    register_attempt_sink,
)
from news_collector.infrastructure.run_context import run_context
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)

SCHEMA_VERSION = 1
DEFAULT_RETENTION_DAYS = 90
_ENV_DISABLE = "NOTICIENCIAS_LLM_METRICS"
_BLANK_KINDS = ("empty_response", "invalid_json")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    run_id TEXT,
    environment TEXT,
    provider TEXT NOT NULL,
    model TEXT,
    purpose TEXT NOT NULL,
    ok INTEGER NOT NULL,
    kind TEXT,
    latency_ms INTEGER NOT NULL,
    failover_index INTEGER NOT NULL,
    error TEXT,
    queue_wait_ms INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_ts ON llm_calls(ts);
CREATE INDEX IF NOT EXISTS idx_llm_calls_provider_ts ON llm_calls(provider, ts);
"""


def _percentile(sorted_values: List[int], pct: float) -> Optional[int]:
    """Nearest-rank percentile of an ascending list (``None`` when empty)."""
    if not sorted_values:
        return None
    rank = max(1, math.ceil(pct / 100.0 * len(sorted_values)))
    return sorted_values[min(rank, len(sorted_values)) - 1]


@dataclass
class ProviderSummary:
    """Aggregated behaviour of one provider/model (optionally per purpose)."""

    provider: str
    model: Optional[str]
    purpose: Optional[str] = None
    calls: int = 0  # real attempts (skips excluded)
    ok: int = 0
    skips: int = 0
    saves: int = 0  # successes served after an earlier provider failed
    blank: int = 0  # empty responses + invalid JSON
    p50_ms: Optional[int] = None
    p95_ms: Optional[int] = None
    kinds: Dict[str, int] = field(default_factory=dict)

    @property
    def success_rate(self) -> Optional[float]:
        return self.ok / self.calls if self.calls else None

    @property
    def blank_rate(self) -> Optional[float]:
        return self.blank / self.calls if self.calls else None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "purpose": self.purpose,
            "calls": self.calls,
            "ok": self.ok,
            "success_rate": self.success_rate,
            "skips": self.skips,
            "saves": self.saves,
            "blank_rate": self.blank_rate,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "kinds": dict(self.kinds),
        }


class LLMMetricsStore:
    """SQLite-backed, fail-open store of :class:`AttemptRecord` rows."""

    def __init__(
        self,
        db_path: Optional[str | Path] = None,
        *,
        environment: Optional[str] = None,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> None:
        self.environment = environment or run_context.get_context().get(
            "environment", "development"
        )
        self.db_path = Path(
            db_path or f"data/metrics/{self.environment}/llm_metrics.db"
        )
        self.retention_days = retention_days
        self.failed_writes = 0
        self._warned = False
        self._lock = threading.Lock()
        self._ready = False
        self._ensure_ready()

    # ---- internals ----

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @contextlib.contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """Transaction that also closes the connection (``with conn`` alone
        commits but leaks the handle)."""
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _ensure_ready(self) -> bool:
        """Create the schema and purge old rows once; ``False`` if unavailable."""
        if self._ready:
            return True
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._session() as conn:
                conn.executescript(_SCHEMA)
                # Additive migration for databases created before queue_wait_ms.
                cols = {r[1] for r in conn.execute("PRAGMA table_info(llm_calls)")}
                if "queue_wait_ms" not in cols:
                    conn.execute(
                        "ALTER TABLE llm_calls ADD COLUMN queue_wait_ms "
                        "INTEGER NOT NULL DEFAULT 0"
                    )
                conn.execute(
                    "DELETE FROM llm_calls WHERE ts < ?",
                    (time.time() - self.retention_days * 86400,),
                )
            self._ready = True
        except (OSError, sqlite3.Error) as err:
            self._note_failure(err)
        return self._ready

    def _note_failure(self, err: BaseException) -> None:
        self.failed_writes += 1
        if not self._warned:
            self._warned = True
            logger.warning(
                "LLM metrics store unavailable ({}); continuing without "
                "persistence (further failures are counted, not logged).",
                err,
            )

    # ---- write path ----

    def record(self, rec: AttemptRecord) -> None:
        """Persist one attempt. Never raises."""
        if not self._ensure_ready():
            self.failed_writes += 1
            return
        try:
            ctx = run_context.get_context()
            with self._lock, self._session() as conn:
                conn.execute(
                    "INSERT INTO llm_calls (ts, run_id, environment, provider, "
                    "model, purpose, ok, kind, latency_ms, failover_index, error, "
                    "queue_wait_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        rec.ts or time.time(),
                        ctx.get("run_id"),
                        self.environment,
                        rec.provider,
                        rec.model,
                        rec.purpose,
                        int(rec.ok),
                        rec.kind.value if rec.kind else None,
                        rec.latency_ms,
                        rec.failover_index,
                        rec.error,
                        rec.queue_wait_ms,
                    ),
                )
        except (sqlite3.Error, OSError) as err:
            self._note_failure(err)

    # ---- read path ----

    def summary(
        self, since_ts: Optional[float] = None, by_purpose: bool = False
    ) -> List[ProviderSummary]:
        """Aggregate rows since ``since_ts`` per provider/model[/purpose]."""
        if not self._ensure_ready():
            return []
        try:
            with self._session() as conn:
                rows = conn.execute(
                    "SELECT provider, model, purpose, ok, kind, latency_ms, "
                    "failover_index FROM llm_calls WHERE ts >= ?",
                    (since_ts or 0.0,),
                ).fetchall()
        except sqlite3.Error as err:
            self._note_failure(err)
            return []
        return _aggregate(rows, by_purpose)


def _aggregate(rows: Iterable[tuple], by_purpose: bool) -> List[ProviderSummary]:
    groups: Dict[tuple, List[tuple]] = {}
    for row in rows:
        provider, model, purpose = row[0], row[1], row[2]
        key = (provider, model, purpose if by_purpose else None)
        groups.setdefault(key, []).append(row)

    out: List[ProviderSummary] = []
    for (provider, model, purpose), items in sorted(
        groups.items(), key=lambda kv: tuple(str(p) for p in kv[0])
    ):
        summary = ProviderSummary(provider, model, purpose)
        latencies: List[int] = []
        kinds: Counter[str] = Counter()
        for _p, _m, _pu, ok, kind, latency_ms, failover_index in items:
            if kind == "degraded_skip":
                summary.skips += 1
                continue
            summary.calls += 1
            if ok:
                summary.ok += 1
                latencies.append(latency_ms)
                if failover_index > 0:
                    summary.saves += 1
            elif kind:
                kinds[kind] += 1
                if kind in _BLANK_KINDS:
                    summary.blank += 1
        summary.kinds = dict(kinds)
        latencies.sort()
        summary.p50_ms = _percentile(latencies, 50)
        summary.p95_ms = _percentile(latencies, 95)
        out.append(summary)
    return out


def format_report(rows: List[ProviderSummary]) -> str:
    """Plain-text table for terminals."""
    if not rows:
        return "No LLM attempts recorded in this window."

    def pct(value: Optional[float]) -> str:
        return "-" if value is None else f"{value * 100:.0f}%"

    def ms(value: Optional[int]) -> str:
        return "-" if value is None else f"{value / 1000:.1f}s"

    header = (
        f"{'provider':<14}{'model':<34}{'purpose':<14}{'calls':>6}{'ok%':>6}"
        f"{'p50':>7}{'p95':>7}{'blank':>7}{'skips':>6}{'saves':>6}  failures"
    )
    lines = [header, "-" * len(header)]
    for r in rows:
        failures = ", ".join(f"{k}={v}" for k, v in sorted(r.kinds.items())) or "-"
        lines.append(
            f"{r.provider:<14}{(r.model or '-')[:32]:<34}{(r.purpose or 'all')[:12]:<14}"
            f"{r.calls:>6}{pct(r.success_rate):>6}{ms(r.p50_ms):>7}{ms(r.p95_ms):>7}"
            f"{pct(r.blank_rate):>7}{r.skips:>6}{r.saves:>6}  {failures}"
        )
    return "\n".join(lines)


# ------------------------------------------------------------- default wiring

_default_store: Optional[LLMMetricsStore] = None
_install_lock = threading.Lock()


def install_default_metrics_sink() -> Optional[LLMMetricsStore]:
    """Register the process-wide store as an attempt sink (idempotent).

    Skipped when ``NOTICIENCIAS_LLM_METRICS=0`` and under pytest, so test runs
    never write to a developer's metrics database.
    """
    global _default_store
    if os.environ.get(_ENV_DISABLE, "1") == "0" or "PYTEST_CURRENT_TEST" in os.environ:
        return None
    with _install_lock:
        if _default_store is None:
            _default_store = LLMMetricsStore()
            register_attempt_sink(_default_store.record)
        return _default_store
