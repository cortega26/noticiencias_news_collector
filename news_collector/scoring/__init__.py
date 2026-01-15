"""Scoring package exports."""

from news_collector.config import SCORING_CONFIG

from .basic_scorer import BasicScorer
from .basic_scorer import score_multiple_articles as _basic_score_multiple
from .feature_scorer import FeatureBasedScorer
from .cognitive_scorer import CognitiveScorer
from .interfaces import AsyncScorer

from news_collector.utils.llm_client import LLMClient

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
    "cognitive_engagement": 0.40
}


def create_scorer(weights=None, mode: str | None = None):
    """Factory returning the configured scorer implementation."""
    selected_mode = (mode or SCORING_CONFIG.get("mode", "advanced")).lower()
    print(f"DEBUG: create_scorer selected_mode={selected_mode} (from config: {SCORING_CONFIG.get('mode')})")
    
    if selected_mode == "cognitive":
        # Create LLM Client with model from config if specified
        llm_model = SCORING_CONFIG.get("llm_model")
        llm_client = None
        if llm_model:
            print(f"DEBUG: Initializing LLM Client with model: {llm_model}")
            llm_client = LLMClient(model=llm_model)

        # Supports dynamic weight adjustment from UI
        return CognitiveScorer(
            weights=weights or SCORING_CONFIG.get("weights", COGNITIVE_SCORING_WEIGHTS),
            llm_client=llm_client
        )
        
    if selected_mode == "basic":
        return BasicScorer(
            weights or SCORING_CONFIG.get("weights", DEFAULT_SCORING_WEIGHTS)
        )
    
    # Default/Advanced
    return FeatureBasedScorer(SCORING_CONFIG)


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
