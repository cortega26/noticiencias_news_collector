"""Per-host pacing for article-page fetches (plan 116).

Burst-driven 403/429s from publishers (schneier, biorxiv, restofworld, ...)
come from back-to-back article requests to one host: the enrichment hot path
fires sequential fetches with zero inter-request delay. ``HostPacer`` turns
those bursts into polite sequential traffic without serializing *across*
hosts:

- a per-host minimum interval between fetch starts (default 1.5 s), and
- a per-host concurrency cap (default 1 = strictly sequential per host).

The pacer is thread-safe and shared via injection (the router owns one
instance; collectors share the router), so concurrent source fan-out still
paces correctly. Waits never hold the registry lock, so hosts never block
each other. All waits are bounded (``max_wait_seconds``): on timeout the
fetch proceeds unpaced (fail-open) rather than deadlocking.

Zero knobs disable pacing while preserving current behavior:
``min_interval_seconds=0`` removes the interval, ``max_concurrency=0``
removes the cap. ``HostPacer.disabled()`` builds that passthrough.

The clock/sleep callables are injectable so tests never sleep for real
(the tenacity ``nap.sleep`` seam is the house pattern for retry waits and
is the default here too).
"""

from __future__ import annotations

import contextlib
import threading
import time
from typing import Callable, Dict, Iterator, Optional
from urllib.parse import urlparse

from tenacity.nap import sleep as tenacity_sleep

from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)

DEFAULT_MIN_INTERVAL_SECONDS = 1.5
DEFAULT_MAX_CONCURRENCY = 1
DEFAULT_MAX_WAIT_SECONDS = 60.0


def _normalize_host(url: str) -> str:
    """Lowercased ``netloc`` for pacing buckets; ``""`` when unparseable."""
    try:
        return urlparse(url or "").netloc.lower()
    except Exception:  # fail-open: unparseable URLs skip pacing
        return ""


class _HostSlot:
    """Mutable per-host pacing state. Guarded by its own lock."""

    __slots__ = ("lock", "next_allowed", "semaphore")

    def __init__(self, max_concurrency: int) -> None:
        self.lock = threading.Lock()
        # Monotonic timestamp at/after which the next fetch may start.
        self.next_allowed = 0.0
        self.semaphore: Optional[threading.Semaphore] = (
            threading.Semaphore(max_concurrency) if max_concurrency > 0 else None
        )


class HostPacer:
    """Thread-safe per-host minimum-interval + concurrency-cap throttle."""

    def __init__(
        self,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = tenacity_sleep,
    ) -> None:
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds must be >= 0")
        if max_concurrency < 0:
            raise ValueError("max_concurrency must be >= 0")
        if max_wait_seconds < 0:
            raise ValueError("max_wait_seconds must be >= 0")
        self._min_interval = float(min_interval_seconds)
        self._max_concurrency = int(max_concurrency)
        self._max_wait = float(max_wait_seconds)
        self._clock = clock
        self._sleep = sleep
        self._registry_lock = threading.Lock()
        self._slots: Dict[str, _HostSlot] = {}

    @classmethod
    def disabled(cls) -> "HostPacer":
        """Passthrough pacer: no interval, no cap (preserves current behavior)."""
        return cls(min_interval_seconds=0, max_concurrency=0)

    @property
    def enabled(self) -> bool:
        return self._min_interval > 0 or self._max_concurrency > 0

    @staticmethod
    def host_for_url(url: str) -> str:
        return _normalize_host(url)

    def _slot_for(self, host: str) -> _HostSlot:
        # Fast path under the registry lock only; waits never hold it, so a
        # slow host can never serialize unrelated hosts (plan 116 STOP guard).
        with self._registry_lock:
            slot = self._slots.get(host)
            if slot is None:
                slot = _HostSlot(self._max_concurrency)
                self._slots[host] = slot
            return slot

    def _wait_for_interval(self, host: str, slot: _HostSlot) -> None:
        if self._min_interval <= 0:
            return
        now = self._clock()
        with slot.lock:
            wait = slot.next_allowed - now
        if wait <= 0:
            with slot.lock:
                slot.next_allowed = max(now, slot.next_allowed) + self._min_interval
            return
        if wait > self._max_wait:
            logger.warning(
                {
                    "event": "enrichment.pacer.interval_truncated",
                    "details": {"host": host, "wait": wait, "cap": self._max_wait},
                }
            )
            wait = self._max_wait
        self._sleep(wait)
        now = self._clock()
        with slot.lock:
            slot.next_allowed = max(now, slot.next_allowed) + self._min_interval

    @contextlib.contextmanager
    def pace(self, url: str) -> Iterator[None]:
        """Hold a per-host fetch slot for the wrapped fetch call.

        Releases the concurrency slot even when the fetch raises or times
        out (``finally``), so a failing host cannot wedge later fetches.
        Fail-open: unparseable URLs, disabled knobs, and slot-acquire
        timeouts all proceed without pacing rather than blocking.
        """
        host = _normalize_host(url)
        if not host or not self.enabled:
            yield
            return
        slot = self._slot_for(host)
        acquired = True
        if slot.semaphore is not None:
            acquired = slot.semaphore.acquire(timeout=self._max_wait)
            if not acquired:
                logger.warning(
                    {
                        "event": "enrichment.pacer.slot_timeout",
                        "details": {"host": host, "cap": self._max_wait},
                    }
                )
                yield
                return
        try:
            self._wait_for_interval(host, slot)
            yield
        finally:
            if acquired and slot.semaphore is not None:
                slot.semaphore.release()
