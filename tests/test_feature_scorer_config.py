from __future__ import annotations

import copy
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from config.settings import SCORING_CONFIG
from src.scoring.feature_scorer import FeatureBasedScorer


def _article_factory(**overrides):
    metadata_override = overrides.pop("article_metadata", {})
    metadata = {
        "normalized_title": "baseline science title",  # ~24 chars
        "normalized_summary": "baseline science summary" * 5,
        "enrichment": {"entities": [], "sentiment": "neutral"},
        "source_metadata": {"credibility_score": 0.7},
        "engagement_features": {},
    }
    metadata.update(metadata_override)

    return SimpleNamespace(
        id="test-article",
        title="Science advances",
        summary="Detailed overview of recent discoveries." * 3,
        published_date=overrides.get(
            "published_date", datetime(2025, 1, 1, tzinfo=timezone.utc)
        ),
        word_count=overrides.get("word_count", 400),
        duplication_confidence=overrides.get("duplication_confidence", 0.0),
        article_metadata=metadata,
    )


def test_content_quality_weights_respected() -> None:
    config = copy.deepcopy(SCORING_CONFIG)
    config["content_quality_heuristics"] = {
        "title_length_divisor": 100.0,
        "summary_length_divisor": 200.0,
        "entity_target_count": 3.0,
        "weights": {"title": 0.2, "summary": 0.3, "entity": 0.5},
    }

    article = _article_factory(
        article_metadata={
            "normalized_title": "t" * 80,
            "normalized_summary": "s" * 300,
            "enrichment": {"entities": [{}, {}, {}, {}], "sentiment": "neutral"},
        }
    )

    scorer = FeatureBasedScorer(config)
    result = scorer.score_article(article)

    assert result["components"]["content_quality"] == pytest.approx(0.96, abs=1e-6)


def test_engagement_heuristics_pull_from_config() -> None:
    config = copy.deepcopy(SCORING_CONFIG)
    config["engagement_heuristics"] = {
        "sentiment_scores": {"positive": 0.9, "negative": 0.1, "neutral": 0.2},
        "fallback_sentiment": 0.2,
        "word_count_divisor": 1000.0,
        "external_weight": 0.7,
        "length_weight": 0.3,
    }

    article = _article_factory(
        word_count=500,
        article_metadata={
            "enrichment": {"sentiment": "positive", "entities": []},
        },
    )

    scorer = FeatureBasedScorer(config)
    result = scorer.score_article(article)

    expected_engagement = 0.7 * 0.9 + 0.3 * min(500 / 1000.0, 1.0)
    assert result["components"]["engagement"] == pytest.approx(
        expected_engagement, abs=1e-6
    )


def test_invalid_divisors_raise_value_error() -> None:
    config = copy.deepcopy(SCORING_CONFIG)
    config["content_quality_heuristics"] = {
        "title_length_divisor": 0.0,
        "summary_length_divisor": 200.0,
        "entity_target_count": 5.0,
        "weights": {"title": 0.4, "summary": 0.4, "entity": 0.2},
    }

    with pytest.raises(ValueError, match="title_length_divisor"):
        FeatureBasedScorer(config)


def test_diversity_penalty_remains_deterministic() -> None:
    config = copy.deepcopy(SCORING_CONFIG)
    config["diversity_penalty"] = {"weight": 0.5, "max_penalty": 1.0}

    scorer = FeatureBasedScorer(config)
    article = _article_factory(duplication_confidence=0.4)

    result = scorer.score_article(article)

    assert result["penalties"]["diversity_penalty"] == pytest.approx(0.2, abs=1e-6)
