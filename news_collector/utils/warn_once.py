"""One WARNING per key per process, for persistent non-fatal failures.

A fail-open fallback (default config, empty result, skipped check) must still be
loud, but a failure that repeats on every call would drown the log. Use this
instead of ``logger.debug`` or a bare ``except: return None``.
"""

from __future__ import annotations

import threading
from typing import Any

_LOCK = threading.Lock()
_SEEN: set[str] = set()


def first_time(key: str) -> bool:
    """True only the first time ``key`` is seen in this process."""
    with _LOCK:
        if key in _SEEN:
            return False
        _SEEN.add(key)
        return True


def warn_once(logger: Any, key: str, message: str, *args: Any) -> bool:
    """Log ``message`` at WARNING the first time ``key`` is seen.

    ``message`` uses ``{}`` placeholders, like the project loggers. Returns
    True when it was logged.
    """
    if not first_time(key):
        return False
    logger.warning(message, *args)
    return True


def reset() -> None:
    """Forget every key (tests / long-lived services)."""
    with _LOCK:
        _SEEN.clear()
