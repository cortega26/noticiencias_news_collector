"""Unit tests for the cache-backed stage runner (plan 060 Phase 7c-3).

Exercises `run_cached_stage` in isolation from `EditorAgent`: every
collaborator is a recording callback, so the tests pin the runner contract
(cache-hit load, unusable-cache regeneration, single persist path) without
mocking the subject.
"""

from __future__ import annotations

import pytest

from news_collector.components.editorial.editorial_cached_stage import (
    CachedStageHooks,
    CachedStageOutcome,
    run_cached_stage,
)
from news_collector.components.editorial.editorial_stages import EditorialStage


def test_cache_hit_returns_cached_value_without_generating() -> None:
    loaded: list[str] = []
    generated: list[str] = []
    persisted: list[str] = []

    result = run_cached_stage(
        EditorialStage.TRANSLATION,
        CachedStageHooks(
            load_cached=lambda: loaded.append("called") or "cached translation",
            generate=lambda: generated.append("called") or "fresh",
            persist=lambda value: persisted.append(value),
        ),
        cache_present=True,
    )

    assert result == CachedStageOutcome(
        stage=EditorialStage.TRANSLATION,
        value="cached translation",
        from_cache=True,
    )
    assert loaded == ["called"]
    assert generated == []
    assert persisted == []


def test_unusable_cache_regenerates_and_persists() -> None:
    persisted: list[str] = []

    result = run_cached_stage(
        EditorialStage.TRANSLATION,
        CachedStageHooks(
            load_cached=lambda: None,
            generate=lambda: "fresh",
            persist=lambda value: persisted.append(value),
        ),
        cache_present=True,
    )

    assert result.value == "fresh"
    assert result.from_cache is False
    assert persisted == ["fresh"]


def test_missing_cache_never_loads_and_persists() -> None:
    loaded: list[str] = []
    persisted: list[dict] = []
    payload = {"summary_points": ["punto"], "sources": [{"url": "https://x"}]}

    result = run_cached_stage(
        EditorialStage.ENRICHMENT,
        CachedStageHooks(
            load_cached=lambda: loaded.append("called") or None,
            generate=lambda: payload,
            persist=lambda value: persisted.append(value),
        ),
        cache_present=False,
    )

    assert result.stage == EditorialStage.ENRICHMENT
    assert result.value is payload
    assert result.from_cache is False
    assert loaded == []
    assert persisted == [payload]


def test_generated_value_passes_through_unchanged() -> None:
    payload = {"fact_check": [{"label": "x", "status": "confirmed"}]}

    result = run_cached_stage(
        EditorialStage.ENRICHMENT,
        CachedStageHooks(
            load_cached=lambda: None,
            generate=lambda: payload,
            persist=lambda value: None,
        ),
        cache_present=True,
    )

    assert result.value is payload
    assert result.from_cache is False


def test_generate_failure_propagates_without_persisting() -> None:
    persisted: list[str] = []

    def fail_generate() -> str:
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError, match="provider down"):
        run_cached_stage(
            EditorialStage.TRANSLATION,
            CachedStageHooks(
                load_cached=lambda: None,
                generate=fail_generate,
                persist=lambda value: persisted.append(value),
            ),
            cache_present=False,
        )

    assert persisted == []
