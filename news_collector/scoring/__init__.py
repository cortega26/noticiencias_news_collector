"""Scoring package exports."""

from news_collector.config.settings import get_runtime_config

from .basic_scorer import BasicScorer
from .basic_scorer import score_multiple_articles as _basic_score_multiple
from .cognitive_scorer import CognitiveScorer
from .feature_scorer import FeatureBasedScorer
from .interfaces import AsyncScorer

DEFAULT_SCORING_WEIGHTS = {
    "source_credibility": 0.25,
    "recency": 0.20,
    "content_quality": 0.25,
    "engagement_potential": 0.30,
}

COGNITIVE_SCORING_WEIGHTS = {
    "source_credibility": 0.20,
    "recency": 0.20,
    "content_quality": 0.20,
    "cognitive_engagement": 0.40,
}


def create_scorer(weights=None, mode: str | None = None):
    """Factory returning the configured scorer implementation."""
    scoring_config = get_runtime_config().scoring_config
    selected_mode = (mode or scoring_config.get("mode", "advanced")).lower()
    print(
        f"DEBUG: create_scorer selected_mode={selected_mode} "
        f"(from config: {scoring_config.get('mode')})"
    )

    if selected_mode == "cognitive":
        llm_client = None

        # Supports dynamic weight adjustment from UI
        return CognitiveScorer(
            weights=weights or scoring_config.get("weights", COGNITIVE_SCORING_WEIGHTS),
            llm_client=llm_client,
        )

    if selected_mode == "basic":
        return BasicScorer(
            weights or scoring_config.get("weights", DEFAULT_SCORING_WEIGHTS)
        )

    # Default/Advanced
    return FeatureBasedScorer(scoring_config)


def get_default_scorer():
    """Return scorer using configuration defaults."""
    return create_scorer()


def score_multiple_articles(articles, scorer=None):
    scorer = scorer or get_default_scorer()
    if isinstance(scorer, BasicScorer):
        # CognitiveScorer inherits from BasicScorer, so this might work,
        # but check if _basic_score_multiple is compatible.
        # _basic_score_multiple usually iterates and calls score_article.
        return _basic_score_multiple(articles, scorer)

    results = []
    for article in articles:
        results.append(scorer.score_article(article))
    return results


__all__ = [
    "AsyncScorer",
    "BasicScorer",
    "FeatureBasedScorer",
    "CognitiveScorer",
    "score_multiple_articles",
    "DEFAULT_SCORING_WEIGHTS",
    "COGNITIVE_SCORING_WEIGHTS",
    "create_scorer",
    "get_default_scorer",
]
