from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from news_collector.collectors.rss_collector import RSSCollector


@patch("news_collector.collectors.rss_collector.enrichment_pipeline")
class TestQualityContract:

    @pytest.fixture
    def collector(self):
        db_manager = MagicMock()
        # Mock storage calls to avoid DB errors
        db_manager.save_article.return_value = MagicMock()
        return RSSCollector(db_manager)

    @pytest.fixture
    def source_config(self):
        return {
            "name": "Test Source",
            "category": "science",
            "credibility_score": 0.9,
            "min_content_length": 500,
        }

    @pytest.fixture
    def mock_enrich_data(self):
        return {
            "entities": [],
            "topics": [],
            "sentiment": "neutral",
            "language": "en",
            "normalized_title": "Title",
            "normalized_summary": "Summary",
            "model_version": "test_v1",
        }

    def test_stage_a_allows_short_candidates(
        self, mock_enrich, collector, source_config, mock_enrich_data
    ):
        """
        Verify that extremely short articles are NOT rejected by Pydantic model
        (Stage A: Discovery).
        """
        # Mock enrichment
        mock_enrich.enrich_article.return_value = mock_enrich_data

        raw_article = {
            "url": "http://example.com/short",
            "title": "Valid Title for Short Article",
            "summary": "This is a very short summary, less than 500 chars.",
            "content": "",
            "published_date": datetime.now(timezone.utc),
            "source_metadata": {},
        }

        model = collector._process_article(raw_article, "test_source", source_config)

        assert model is not None
        assert str(model.url) == "https://example.com/short"
        # However, it should be marked as FAILED STAGE B
        assert model.processing_status_override == "rejected"

    def test_stage_b_enforces_limit_failure(
        self, mock_enrich, collector, source_config, mock_enrich_data
    ):
        """
        Verify that short content fails Stage B (Enrichment) and gets
        marked as 'rejected'.
        """
        mock_enrich.enrich_article.return_value = mock_enrich_data

        short_text = (
            "This content is definitely less than 500 characters. " * 5
        )  # ~250 chars
        raw_article = {
            "url": "http://example.com/failed_enrichment",
            "title": "Title is now long enough for validation",
            "summary": "Summary is also long enough",
            "content": short_text,
            "published_date": datetime.now(timezone.utc),
            "source_metadata": {},
        }

        model = collector._process_article(raw_article, "test_source", source_config)

        assert model is not None
        assert len(model.content) < 500
        assert model.processing_status_override == "rejected"

    def test_stage_b_enforces_limit_success(
        self, mock_enrich, collector, source_config, mock_enrich_data
    ):
        """
        Verify that long content passes Stage B and stays 'pending' (ready for publish).
        """
        mock_enrich.enrich_article.return_value = mock_enrich_data

        long_text = "This content is long enough to be published. " * 30  # > 1000 chars
        raw_article = {
            "url": "http://example.com/success",
            "title": "Title is now long enough for validation",
            "summary": "Summary is also long enough",
            "content": long_text,
            "published_date": datetime.now(timezone.utc),
            "source_metadata": {},
        }

        model = collector._process_article(raw_article, "test_source", source_config)

        assert model is not None
        assert len(model.content) >= 500
        # Should be None (default) or explicit 'pending' if we set it?
        # Our logic leaves it None if successful, assuming DB default is PENDING.
        assert model.processing_status_override is None

    def test_summary_only_fails_stage_b_if_short(
        self, mock_enrich, collector, source_config, mock_enrich_data
    ):
        """
        Even if content_mode is summary_only, if it's short, it shouldn't be published.
        """
        mock_enrich.enrich_article.return_value = mock_enrich_data

        source_config["content_mode"] = "summary_only"
        raw_article = {
            "url": "http://example.com/summary_mode",
            "title": "Title is now long enough for validation",
            "summary": "Short summary only.",
            "content": None,
            "published_date": datetime.now(timezone.utc),
            "source_metadata": {},
            "content_mode": "summary_only",
        }

        model = collector._process_article(raw_article, "test_source", source_config)

        assert model is not None
        # Should fail because 500 char limit applies to PUBLICATION
        assert model.processing_status_override == "rejected"
