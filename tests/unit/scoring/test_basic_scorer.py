from datetime import datetime, timedelta, timezone

import pytest
from news_collector.scoring.basic_scorer import BasicScorer
from news_collector.storage.models import Article


@pytest.fixture
def basic_scorer():
    return BasicScorer(
        weights={
            "source_credibility": 0.25,
            "recency": 0.25,
            "content_quality": 0.25,
            "engagement_potential": 0.25,
        }
    )


@pytest.fixture
def sample_article():
    return Article(
        id="1",
        url="http://test.com/1",
        title="New Study on Climate Change",
        summary="A comprehensive study regarding carbon emissions.",
        content="Full content of the study goes here and it is quite long to satisfy length requirements.",
        source_id="s1",
        source_name="Science Daily",
        category="science",
        published_date=datetime.now(timezone.utc),
        collected_date=datetime.now(timezone.utc),
        authors=["Alice Scientist"],
        language="en",
        article_metadata={"credibility_score": 0.8},
    )


def test_score_article_flow(basic_scorer, sample_article):
    result = basic_scorer.score_article(sample_article)
    assert result["final_score"] >= 0.0
    assert "components" in result
    assert "explanation" in result


def test_source_credibility(basic_scorer, sample_article):
    # Base
    sample_article.article_metadata["credibility_score"] = 0.5
    s1 = basic_scorer._calculate_source_credibility_score(sample_article)

    # + Peer Review
    sample_article.peer_reviewed = True
    s2 = basic_scorer._calculate_source_credibility_score(sample_article)
    assert s2 > s1

    # + DOI
    sample_article.doi = "10.1000/xyz"
    s3 = basic_scorer._calculate_source_credibility_score(sample_article)
    assert s3 > s2

    # Elite Journal
    sample_article.journal = "Nature"
    s4 = basic_scorer._calculate_source_credibility_score(sample_article)
    assert s4 > s3


def test_recency_decay(basic_scorer, sample_article):
    now = datetime.now(timezone.utc)

    # 1 hour old
    sample_article.published_date = now - timedelta(hours=1)
    s1 = basic_scorer._calculate_recency_score(sample_article)
    assert s1 == pytest.approx(1.0)  # Max score for first hour

    # 25 hours old
    sample_article.published_date = now - timedelta(hours=25)
    s2 = basic_scorer._calculate_recency_score(sample_article)
    assert s2 < 0.9  # Should decay

    # 1 week old
    sample_article.published_date = now - timedelta(hours=168)
    s3 = basic_scorer._calculate_recency_score(sample_article)
    assert s3 < s2


def test_recency_reaches_zero_at_candidate_cutoff(basic_scorer, sample_article):
    """Plan 050: recency must hit 0.0 at the candidate age cutoff and be
    ~0.00 a minute before it — no 0.05 floor."""
    now = datetime.now(timezone.utc)

    # 29d23h59m old → effectively 0.00
    sample_article.published_date = now - timedelta(days=29, hours=23, minutes=59)
    s_at_limit = basic_scorer._calculate_recency_score(sample_article)
    assert 0.0 <= s_at_limit < 0.001

    # Exactly 30 days (candidate_max_age_days=30) → 0.0
    sample_article.published_date = now - timedelta(days=30)
    assert basic_scorer._calculate_recency_score(sample_article) == 0.0

    # Well beyond (45d, 90d) → 0.0
    sample_article.published_date = now - timedelta(days=45)
    assert basic_scorer._calculate_recency_score(sample_article) == 0.0
    sample_article.published_date = now - timedelta(days=90)
    assert basic_scorer._calculate_recency_score(sample_article) == 0.0


def test_recency_monotonic_no_floor(basic_scorer, sample_article):
    """Plan 050: strictly decreasing across the whole 30-day window and no
    visible 0.05 floor below day 30."""
    now = datetime.now(timezone.utc)
    last = None
    for days in (0, 1, 3, 7, 15, 20, 25, 29):
        sample_article.published_date = now - timedelta(days=days)
        s = basic_scorer._calculate_recency_score(sample_article)
        if last is not None:
            assert s < last, f"not monotone at {days}d ({s} >= {last})"
        last = s


def test_quality_metrics(basic_scorer):
    # Title quality
    assert (
        basic_scorer._evaluate_title_quality("Amazing secret!") < 0.5
    )  # clickbait penalty
    assert (
        basic_scorer._evaluate_title_quality(
            "A comprehensive study regarding the effects of X"
        )
        > 0.3
    )  # quality indicator (adjusted for length)

    # Content quality
    high_quality_text = "Analysis of methodology regarding cell protein synthesis."
    assert basic_scorer._evaluate_text_quality(high_quality_text) > 0.5


def test_engagement_metrics(basic_scorer):
    # Trending topics
    article = Article(
        id="2",
        url="u",
        title="AI and ChatGPT",
        summary="...",
        source_id="s",
        source_name="n",
        category="c",
        published_date=datetime.now(timezone.utc),
        collected_date=datetime.now(timezone.utc),
    )
    assert basic_scorer._evaluate_trending_topics(article) > 0

    # Wow factor
    article.title = "First time revolutionary discovery"
    assert basic_scorer._evaluate_wow_factor(article) > 0


@pytest.mark.asyncio
async def test_score_async(basic_scorer, sample_article):
    data = {"article": sample_article.to_dict(), "source_config": {}}
    res = await basic_scorer.score_article_async(data)
    assert res["final_score"] is not None
