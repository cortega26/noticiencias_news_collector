"""Process-wide, in-memory counters for one pipeline run's LLM-vs-heuristic work.

The pipeline has two LLM-dependent stages that silently degrade to heuristics
when the provider chain fails (PreScorer -> deterministic rank, CognitiveScorer
-> heuristic scoring). Each stage records its outcome here so the end-of-run
report (``llm_run_report``) can say how much of the work the LLM really did.

Counters are per *article* (what a reader cares about), thread-safe (the
collectors run in a thread pool) and never raise: recording must not be able
to affect the stage it observes.
"""

from __future__ import annotations

import threading
from collections import Counter
from typing import Dict

_LOCK = threading.Lock()
_COUNTS: "Counter[str]" = Counter()


def record(stage: str, outcome: str, n: int = 1) -> None:
    """Add ``n`` items to ``<stage>.<outcome>`` (e.g. ``scoring.llm``)."""
    if n <= 0:
        return
    try:
        with _LOCK:
            _COUNTS[f"{stage}.{outcome}"] += n
    except Exception:  # noqa: BLE001 - observability must never break a stage
        return


def snapshot() -> Dict[str, int]:
    """Copy of all counters."""
    with _LOCK:
        return dict(_COUNTS)


def reset() -> None:
    with _LOCK:
        _COUNTS.clear()
