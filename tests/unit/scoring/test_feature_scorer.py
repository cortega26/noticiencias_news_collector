import pytest
import math
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
from news_collector.scoring.feature_scorer import FeatureBasedScorer
from news_collector.storage.models import Article

@pytest.fixture
def feature_scorer():
    config = {
        "feature_weights": {"source_credibility": 0.3, "freshness": 0.2, "content_quality": 0.3, "engagement": 0.2},
        "freshness": {"half_life_hours": 12.0, "max_decay_hours": 72.0},
        "diversity_penalty": {"weight": 0.5, "max_penalty": 0.4},
        "minimum_score": 0.1,
        "content_quality_heuristics": {
            "title_length_divisor": 10.0,
            "summary_length_divisor": 20.0,
            "entity_target_count": 5.0,
            "weights": {"title": 0.3, "summary": 0.5, "entity": 0.2}
        },
        "engagement_heuristics": {
            "sentiment_scores": {"positive": 0.8, "negative": 0.6, "neutral": 0.5},
            "word_count_divisor": 100.0,
            "external_weight": 0.5,
            "length_weight": 0.5
        }
    }
    return FeatureBasedScorer(config)

@pytest.fixture
def sample_article():
    return Article(
        id="123",
        url="http://example.com/1",
        title="Valid Title",
        summary="A summary used for scoring content quality.",
        content="Content goes here.",
        source_id="s1",
        source_name="Source 1",
        published_date=datetime.now(timezone.utc),
        collected_date=datetime.now(timezone.utc),
        article_metadata={}
    )

def test_config_validation():
    with pytest.raises(ValueError, match="must be > 0"):
        FeatureBasedScorer({"content_quality_heuristics": {"title_length_divisor": -1}})
    
    with pytest.raises(ValueError, match="weights must sum to 1.0"):
        FeatureBasedScorer({"content_quality_heuristics": {"weights": {"title": 0.1, "summary": 0.1, "entity": 0.1}}})

def test_source_credibility_default(feature_scorer, sample_article):
    # No metadata
    assert feature_scorer._source_credibility(sample_article, None) == 0.5
    
    # In source config
    assert feature_scorer._source_credibility(sample_article, {"credibility_score": 0.9}) == 0.9
    
    # In article metadata
    sample_article.article_metadata["credibility_score"] = 0.7
    assert feature_scorer._source_credibility(sample_article, None) == 0.7

def test_freshness_score(feature_scorer, sample_article):
    # Now -> 1.0
    assert feature_scorer._freshness_score(sample_article) == pytest.approx(1.0, rel=1e-5)
    
    # 12 hours old (half life) -> 0.5
    sample_article.published_date = datetime.now(timezone.utc) - timedelta(hours=12)
    score = feature_scorer._freshness_score(sample_article)
    assert 0.49 < score < 0.51
    
    # Very old -> 0.0
    sample_article.published_date = datetime.now(timezone.utc) - timedelta(hours=100)
    assert feature_scorer._freshness_score(sample_article) == 0.0

def test_content_quality(feature_scorer, sample_article):
    # Title len=11 (>10 divisor) -> cap 1.0 * 0.3 weight = 0.3
    # Summary len=43 (>20 divisor) -> cap 1.0 * 0.5 weight = 0.5
    # Entities 0 -> 0.0
    # Total = 0.8
    score = feature_scorer._content_quality_score(sample_article)
    assert score == pytest.approx(0.8)

    # With normalized fields
    sample_article.article_metadata["normalized_title"] = "Short" # 5 chars / 10 = 0.5 * 0.3 = 0.15
    sample_article.article_metadata["normalized_summary"] = "Short" # 5 chars / 20 = 0.25 * 0.5 = 0.125
    # Entities
    sample_article.article_metadata["enrichment"] = {"entities": ["A", "B", "C", "D", "E"]} # 5/5 = 1.0 * 0.2 = 0.2
    # Total = 0.15 + 0.125 + 0.2 = 0.475
    score2 = feature_scorer._content_quality_score(sample_article)
    assert score2 == pytest.approx(0.475)

def test_engagement_score(feature_scorer, sample_article):
    # Sentiment
    sample_article.article_metadata["enrichment"] = {"sentiment": "positive"} # 0.8
    # Word count (default 400), divisor 100 -> capped 1.0
    # External score None -> uses sentiment 0.8
    
    # Formula: 0.5 * 0.8 (external) + 0.5 * 1.0 (length) = 0.4 + 0.5 = 0.9
    score = feature_scorer._engagement_score(sample_article)
    assert score == pytest.approx(0.9)
    
    # With external engagement score
    sample_article.article_metadata["engagement_features"] = {"score": 0.2}
    # 0.5 * 0.2 + 0.5 * 1.0 = 0.1 + 0.5 = 0.6
    assert feature_scorer._engagement_score(sample_article) == pytest.approx(0.6)

def test_diversity_penalty(feature_scorer, sample_article):
    # High confidence duplication
    sample_article.duplication_confidence = 0.8
    # Penalty: 0.5 * 0.8 = 0.4 (capped at 0.4)
    penalty, reason = feature_scorer._diversity_penalty(sample_article)
    assert penalty == pytest.approx(0.4)
    assert "0.80" in reason

def test_full_scoring_flow(feature_scorer, sample_article):
    res = feature_scorer.score_article(sample_article)
    assert "final_score" in res
    assert "components" in res
    assert "explanation" in res
    assert res["should_include"] is True # 0.1 min score

def test_async_score(feature_scorer, sample_article):
    import asyncio
    data = {"article": sample_article.to_dict(), "source_config": {}}
    res = asyncio.run(feature_scorer.score_article_async(data))
    assert "final_score" in res
