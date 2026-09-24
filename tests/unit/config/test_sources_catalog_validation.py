"""Unit coverage for the source-catalog module surface used by plan 060/4b.

Exercises the pure catalog validator branch-by-branch, the loader's
missing-file and corrupt-file paths, the YAML round-trip, the group
buckets, the query helpers, and the strategy-audit entry points — all
against isolated fixtures or the untouched real catalog. Any test that
mutates the module globals restores them via `load_sources()` so the rest
of the suite keeps seeing the real catalog.
"""

from __future__ import annotations

import pytest
import yaml

from news_collector.config import sources as sources_mod
from news_collector.config.sources import (
    ALL_SOURCES,
    collect_source_strategy_audit,
    get_high_credibility_sources,
    get_sources_by_category,
    get_sources_by_tier,
    get_sources_by_update_frequency,
    load_sources,
    save_sources,
    validate_source_catalog,
)

VALID_ENTRY = {
    "name": "Example",
    "url": "https://example.com/feed",
    "credibility_score": 0.8,
    "category": "science",
    "tier": "B",
    "fetchability_score": 80,
    "crawl_interval_seconds": 3600,
}


def _entry(**overrides):
    merged = dict(VALID_ENTRY)
    merged.update(overrides)
    return merged


@pytest.fixture(autouse=True)
def _restore_real_catalog():
    """Tests here mutate the module globals via patched YAML paths; reload
    the real catalog after each test. Fixture teardown runs after monkeypatch
    is undone, so this reads the tracked file, not the fixture."""
    yield
    load_sources()


def test_validate_source_catalog_accepts_a_complete_entry() -> None:
    assert validate_source_catalog({"ok": _entry()}) == []


def test_validate_source_catalog_reports_every_missing_field() -> None:
    errors = validate_source_catalog({"bad": {}})

    assert len(errors) == 7
    assert any("missing required field: 'tier'" in e for e in errors)


def test_validate_source_catalog_rejects_each_invalid_rule() -> None:
    cases = [
        ({"tier": "Z"}, "invalid tier"),
        ({"fetchability_score": "high"}, "invalid fetchability_score"),
        ({"fetchability_score": 150}, "invalid fetchability_score"),
        ({"crawl_interval_seconds": 0}, "invalid crawl_interval_seconds"),
        ({"crawl_interval_seconds": "hourly"}, "invalid crawl_interval_seconds"),
        ({"enrichment_strategy": "telepathy"}, "invalid enrichment_strategy"),
        (
            {"enrichment_strategy": "headless_fallback"},
            "must specify 'headless_enabled'",
        ),
        (
            {
                "enrichment_strategy": "headless_fallback",
                "headless_enabled": True,
                "headless_max_seconds": -1,
            },
            "invalid headless_max_seconds",
        ),
        (
            {"blacklisted": True},
            "missing 'blacklist_reason'",
        ),
        (
            {"blacklisted": True, "blacklist_reason": "spam"},
            "missing 'blacklisted_date'",
        ),
    ]
    for override, fragment in cases:
        errors = validate_source_catalog({"x": _entry(**override)})
        assert any(fragment in e for e in errors), (override, errors)


def test_validate_source_catalog_surfaces_audit_inconsistencies() -> None:
    stealth = _entry(enrichment_strategy="scrapling_stealth")
    assert any(
        "headless_enabled is false" in e
        for e in validate_source_catalog({"x": stealth})
    )

    rss_only = _entry(
        enrichment_strategy="scrapling_stealth",
        headless_enabled=True,
        fetch_mode="rss_only",
    )
    assert any("rss_only" in e for e in validate_source_catalog({"x": rss_only}))

    explicit_false = _entry(
        enrichment_strategy="scrapling_stealth", headless_enabled=False
    )
    assert any(
        "cannot use scrapling_stealth while headless is disabled" in e
        for e in validate_source_catalog({"x": explicit_false})
    )


def test_load_sources_missing_file_warns_without_raising(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        sources_mod, "SOURCES_YAML_PATH", tmp_path / "does-not-exist.yaml"
    )

    load_sources()  # must not raise; globals keep their previous content

    assert "not found" in capsys.readouterr().out


def test_load_sources_corrupt_file_prints_and_keeps_process_alive(
    tmp_path, monkeypatch, capsys
) -> None:
    corrupt = tmp_path / "sources.yaml"
    corrupt.write_text("{unclosed: [", encoding="utf-8")
    monkeypatch.setattr(sources_mod, "SOURCES_YAML_PATH", corrupt)
    load_sources()  # prints the error; must not raise

    assert "Error loading sources.yaml" in capsys.readouterr().out


def test_save_sources_round_trips_through_an_isolated_path(
    tmp_path, monkeypatch
) -> None:
    target = tmp_path / "sources.yaml"
    monkeypatch.setattr(sources_mod, "SOURCES_YAML_PATH", target)
    save_sources({"solo": _entry()})

    assert yaml.safe_load(target.read_text(encoding="utf-8"))["solo"]["name"] == (
        "Example"
    )
    assert sources_mod.ALL_SOURCES["solo"]["name"] == "Example"


def test_load_sources_buckets_every_group(tmp_path, monkeypatch) -> None:
    groups = [
        "ELITE_JOURNALS",
        "SCIENCE_MEDIA",
        "INSTITUTIONAL_SOURCES",
        "PREPRINT_SOURCES",
        "COMMUNITY_FEEDS",
        "AI_LABS",
    ]
    catalog = {g.lower(): _entry(**{"_group": g}) for g in groups}
    target = tmp_path / "sources.yaml"
    target.write_text(yaml.safe_dump(catalog), encoding="utf-8")
    monkeypatch.setattr(sources_mod, "SOURCES_YAML_PATH", target)
    load_sources()

    assert sources_mod.ELITE_JOURNALS
    assert sources_mod.SCIENCE_MEDIA
    assert sources_mod.INSTITUTIONAL_SOURCES
    assert sources_mod.PREPRINT_SOURCES
    assert sources_mod.COMMUNITY_FEEDS
    assert sources_mod.AI_LABS
    assert sources_mod.ALL_SOURCES["elite_journals"]["etag"] is None
    assert sources_mod.ALL_SOURCES["elite_journals"]["last_modified"] is None


def test_query_helpers_read_the_live_catalog() -> None:
    assert isinstance(get_sources_by_category("science"), dict)
    assert isinstance(get_high_credibility_sources(0.0), dict)
    assert isinstance(get_sources_by_update_frequency("daily"), dict)
    assert isinstance(get_sources_by_tier("B"), dict)


def test_collect_source_strategy_audit_returns_only_flagged() -> None:
    audited = collect_source_strategy_audit(
        {
            "clean": _entry(),
            "stealthy": _entry(
                enrichment_strategy="scrapling_stealth", headless_enabled=False
            ),
        }
    )

    assert set(audited) == {"stealthy"}
    assert isinstance(collect_source_strategy_audit({}), dict)
