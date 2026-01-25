"""
Tests for MockArticle contract to ensure coverage.
"""

from news_collector.contracts.mock_article import MockArticle


def test_mock_article_defaults():
    """Verify MockArticle instantiates with valid defaults."""
    article = MockArticle()
    assert article.id == 999999
    assert article.title == "Mock Article for Simulation"

    # Check dictionary conversion
    data = article.to_dict()
    assert data["id"] == 999999
    assert data["source_id"] == "mock-source"
