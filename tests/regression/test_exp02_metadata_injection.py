from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from news_collector.scoring.basic_scorer import BasicScorer
from news_collector.scoring.feature_scorer import FeatureBasedScorer
from news_collector.contracts import ArticleMetadataModel


class MockArticle:
    def __init__(self, **kwargs):
        self.peer_reviewed = False
        self.is_preprint = False
        self.doi = None
        self.journal = None
        self.title = "A standard title"
        self.summary = "A standard summary with enough words."
        self.published_date = datetime.now(timezone.utc)
        self.collected_date = datetime.now(timezone.utc)
        self.word_count = 500
        for k, v in kwargs.items():
            setattr(self, k, v)

    def get(self, key, default=None):
        return getattr(self, key, default)


def test_basic_scorer_rejects_injected_metadata():
    """
    Ensure BasicScorer uses typed ArticleMetadataModel and ignores unmodeled
    injected fields like a fake high credibility_score with unmodeled extras.
    """
    scorer = BasicScorer()

    # Malicious payload with extra fields that would fail ArticleMetadataModel extra="forbid"
    malicious_metadata = {
        "credibility_score": 1.0,  # Try to inflate score
        "malicious_injected_key": "this should cause validation failure if typed properly",
    }

    article = MockArticle(article_metadata=malicious_metadata)

    # Run scoring
    result = scorer.score_article(article)

    # If the trust boundary works, the malicious payload fails validation (or is ignored),
    # and the scorer falls back to the safe default credibility of 0.5.
    # 0.5 * 0.6 = 0.3
    # 0.5 base * 0.6 weight = 0.3
    assert (
        result["components"]["source_credibility"] == 0.3
    ), "Score was inflated by injected metadata"


def test_feature_scorer_rejects_injected_metadata():
    """
    Ensure FeatureBasedScorer validates article_metadata via ArticleMetadataModel
    and does not blindly trust raw JSON keys for engagement_features, enrichment, etc.
    """
    scorer = FeatureBasedScorer()

    # Malicious payload injecting nested structures to inflate content_quality and engagement
    malicious_metadata = {
        "credibility_score": 1.0,
        "engagement_features": {"score": 1.0},  # Undeclared field in model
        "enrichment": {
            "entities": [
                "A",
                "B",
                "C",
                "D",
                "E",
                "F",
                "G",
                "H",
                "I",
                "J",
            ],  # Too many? Model caps at 10, but let's test the extra fields.
            "sentiment": "positive",
            "fake_enrichment_key": "to trigger extra=forbid",
        },
        "normalized_title": "Fake normalized title to bypass processing",
        "malicious_key": "raises error in ArticleMetadataModel",
    }

    article = MockArticle(article_metadata=malicious_metadata)

    # Run scoring
    result = scorer.score_article(article)

    # Feature scorer should fall back to defaults (or safe neutral) for metrics when metadata is invalid
    cred_score = result["components"]["source_credibility"]
    eng_score = result["components"]["engagement"]

    assert cred_score < 0.9, "Credibility score was inflated by untyped metadata"
    assert eng_score < 0.8, "Engagement score was inflated by untyped metadata"


def test_exploit_payload_is_neutralized_in_untyped_dict():
    """
    Test the exact payload that previously exploited the feature scorer.
    By submitting credibility_score inside source_metadata, it used to boost credibility to 1.0.
    Now it should NOT boost the score.
    """
    scorer = FeatureBasedScorer()

    # Regression payload from prompt where malicious values are hidden in raw fields
    regression_payload = {
        "source_metadata": {"credibility_score": 1.0, "impact_factor": 99.9},
        "enrichment": {
            "entities": ["Nature", "Nobel Prize"],
            "topics": ["breakthrough"],
            "sentiment": "positive",
            "language": "es",
            "normalized_title": "Fake normalized title",
            "normalized_summary": "Fake normalized summary",
            "model_version": "1.0",
        },
    }

    # Notice we removed "credibility_score": 1.0 from the top level and put it ONLY
    # in source_metadata, which represents the exploit bypassing the typed field.

    article = MockArticle(article_metadata=regression_payload)
    result = scorer.score_article(article)

    cred_score = result["components"]["source_credibility"]
    # Assuming default credibility_score fallback is <= 0.5. If the exploit worked, it would be 1.0.
    assert (
        cred_score <= 0.6
    ), f"Score was inflated by source_metadata injection: {cred_score}"


def test_valid_typed_metadata_is_respected():
    """
    Ensure that when metadata provides perfectly valid, typed data in the correct places,
    it DOES affect the score as intended, proving we haven't broken the intended trust path.
    """
    scorer = FeatureBasedScorer()

    valid_payload = {
        "credibility_score": 1.0,  # Valid top-level typed field
        "source_metadata": {"impact_factor": 99.9},  # Extra details fine in Dict
        "enrichment": {
            "entities": ["Nature", "Nobel Prize"],
            "topics": ["breakthrough"],
            "sentiment": "positive",
            "language": "es",
            "normalized_title": "Fake normalized title",
            "normalized_summary": "Fake normalized summary",
            "model_version": "1.0",
        },
    }

    article = MockArticle(article_metadata=valid_payload)
    result = scorer.score_article(article)

    cred_score = result["components"]["source_credibility"]
    eng_score = result["components"]["engagement"]

    # The score should reflect the 1.0 credibility and positive sentiment
    assert cred_score >= 0.9, "Valid typed credibility score was ignored"
    assert eng_score > 0.6, "Valid typed engagement sentiment was ignored"
