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
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict

from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)

_LOCK = threading.Lock()
_COUNTS: "Counter[str]" = Counter()
_RECORD_ERROR_LOGGED = False


def record(stage: str, outcome: str, n: int = 1) -> None:
    """Add ``n`` items to ``<stage>.<outcome>`` (e.g. ``scoring.llm``)."""
    if n <= 0:
        return
    try:
        with _LOCK:
            _COUNTS[f"{stage}.{outcome}"] += n
    except Exception as err:  # noqa: BLE001 - observability must never break a stage
        global _RECORD_ERROR_LOGGED
        if not _RECORD_ERROR_LOGGED:  # once: this can be hit on every article
            _RECORD_ERROR_LOGGED = True
            logger.warning(
                "LLM run stats could not record {}.{} (n={}): {}; the run "
                "report may undercount.",
                stage,
                outcome,
                n,
                err,
            )


def snapshot() -> Dict[str, int]:
    """Copy of all counters."""
    with _LOCK:
        return dict(_COUNTS)


def reset() -> None:
    with _LOCK:
        _COUNTS.clear()


@dataclass(frozen=True)
class RunScope:
    """Marks the start of one workflow run inside a long-lived process.

    The serving process handles many publications with the same process-wide
    counters; a scope lets each report cover only what happened since it began
    (counter deltas + ``started_at`` for the persisted attempt metrics).
    Concurrent workflows in the same process still share counters.
    """

    started_at: float
    baseline: Dict[str, int] = field(default_factory=dict)


def begin_scope() -> RunScope:
    return RunScope(started_at=time.time(), baseline=snapshot())


def delta_since(scope: RunScope) -> Dict[str, int]:
    """Counters accumulated since ``scope`` began."""
    now = snapshot()
    return {
        key: n - scope.baseline.get(key, 0)
        for key, n in now.items()
        if n - scope.baseline.get(key, 0) > 0
    }
