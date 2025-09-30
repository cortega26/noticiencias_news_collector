"""Scoring package exports."""

from config import SCORING_CONFIG

from .basic_scorer import BasicScorer, score_multiple_articles as _basic_score_multiple
from .feature_scorer import FeatureBasedScorer

DEFAULT_SCORING_WEIGHTS = {
    "source_credibility": 0.25,
    "recency": 0.20,
    "content_quality": 0.25,
    "engagement_potential": 0.30,
}


def create_scorer(weights=None, mode: str | None = None):
    """Factory returning the configured scorer implementation."""
    selected_mode = (mode or SCORING_CONFIG.get("mode", "advanced")).lower()
    if selected_mode == "basic":
        return BasicScorer(
            weights or SCORING_CONFIG.get("weights", DEFAULT_SCORING_WEIGHTS)
        )
    return FeatureBasedScorer(SCORING_CONFIG)


def get_default_scorer():
    """Return scorer using configuration defaults."""
    return create_scorer()


def score_multiple_articles(articles, scorer=None):
    scorer = scorer or get_default_scorer()
    if isinstance(scorer, BasicScorer):
        return _basic_score_multiple(articles, scorer)
    results = []
    for article in articles:
        results.append(scorer.score_article(article))
    return results


__all__ = [
    "BasicScorer",
    "FeatureBasedScorer",
    "score_multiple_articles",
    "DEFAULT_SCORING_WEIGHTS",
    "create_scorer",
    "get_default_scorer",
]
