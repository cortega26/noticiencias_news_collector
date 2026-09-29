"""
Module role: Typed cache-backed stage runner for the EditorAgent stages
(plan 060 Phase 7c-3).

Owns:
- CachedStageOutcome[T]: stage identity + artifact + cache provenance
- CachedStageHooks[T]: load/generate/persist callbacks one stage needs
- run_cached_stage: cache-hit -> load, else generate -> persist

Does NOT own:
- Cache paths (EditorAgent._get_cache_path)
- Artifact parsing/validation and their warnings (caller load closures)
- Prompt construction, LLM calls or provider retries (EditorAgent)
- Retry policy (critic gate) and provenance capture (later 7c slices)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from news_collector.components.editorial.editorial_stages import EditorialStage

T = TypeVar("T")


@dataclass(frozen=True)
class CachedStageOutcome(Generic[T]):
    """One stage artifact and how it was produced."""

    stage: EditorialStage
    value: T
    from_cache: bool


@dataclass(frozen=True)
class CachedStageHooks(Generic[T]):
    """Callbacks one cache-backed stage needs; supplied by `EditorAgent`."""

    load_cached: Callable[[], T | None]
    generate: Callable[[], T]
    persist: Callable[[T], None]


def run_cached_stage(
    stage: EditorialStage,
    hooks: CachedStageHooks[T],
    *,
    cache_present: bool,
) -> CachedStageOutcome[T]:
    """Load a stage artifact from cache or generate and persist it.

    `load_cached` returns None when the cache exists but is unusable (parse
    error, incomplete payload); the runner then regenerates and persists, so
    each caller keeps its own validation warnings and cache I/O. `persist`
    owns its own error handling; the runner does not wrap it.
    """
    if cache_present:
        cached = hooks.load_cached()
        if cached is not None:
            return CachedStageOutcome(stage, cached, True)

    value = hooks.generate()
    hooks.persist(value)
    return CachedStageOutcome(stage, value, False)
