from unittest.mock import patch

import pytest

from news_collector.config.sources import (
    ALL_SOURCES,
    audit_source_strategy_consistency,
    validate_sources,
)


def test_strategy_audit_flags_summary_only_scrapling_without_justification():
    issues = audit_source_strategy_consistency(
        "problem_source",
        {
            "content_mode": "summary_only",
            "enrichment_strategy": "scrapling_stealth",
            "headless_enabled": True,
        },
    )

    assert any("strategy_justification" in issue for issue in issues)


def test_validate_sources_rejects_unjustified_summary_only_scrapling_config():
    bad_sources = {
        "problem_source": {
            "name": "Problem Source",
            "url": "https://example.com/rss.xml",
            "category": "multidisciplinary",
            "language": "en",
            "description": "A flaky source",
            "credibility_score": 0.8,
            "update_frequency": "daily",
            "content_mode": "summary_only",
            "enrichment_strategy": "scrapling_stealth",
            "headless_enabled": True,
            "tier": "B",
            "fetchability_score": 80,
            "crawl_interval_seconds": 3600,
        }
    }

    with pytest.raises(ValueError, match="strategy_justification"):
        with (
            patch("news_collector.config.sources.load_sources"),
            patch.dict(ALL_SOURCES, bad_sources, clear=True),
        ):
            validate_sources()


def test_validate_sources_accepts_justified_summary_only_scrapling_config():
    good_sources = {
        "problem_source": {
            "name": "Problem Source",
            "url": "https://example.com/rss.xml",
            "category": "multidisciplinary",
            "language": "en",
            "description": "A flaky source",
            "credibility_score": 0.8,
            "update_frequency": "daily",
            "content_mode": "summary_only",
            "enrichment_strategy": "scrapling_stealth",
            "strategy_justification": "Nightly audit comparison requires it.",
            "headless_enabled": True,
            "tier": "B",
            "fetchability_score": 80,
            "crawl_interval_seconds": 3600,
        }
    }

    with (
        patch("news_collector.config.sources.load_sources"),
        patch.dict(ALL_SOURCES, good_sources, clear=True),
    ):
        validate_sources()
