from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from news_collector.collectors.rss_collector import RSSCollector


@pytest.mark.regression
def test_enrichment_failure_fail_open():
    """Verify that enrichment failures produce a valid degraded article object."""
    collector = RSSCollector()

    # Mock Enrichment Pipeline using patch
    with patch(
        "news_collector.collectors.rss_collector.enrichment_pipeline.enrich_article",
        side_effect=Exception("API Error"),
    ):
        raw_article = {
            "title": "Enrich Fail Test",
            "url": "http://enrich.fail",
            "link": "http://enrich.fail",
            "published": "Mon, 25 Jan 2026 12:00:00 GMT",
            "published_date": datetime.now(timezone.utc),
            "summary": "Summary",
            "content": "Content " * 100,
            "full_text": "Content " * 100,
            "word_count": 500,
            "reading_time_minutes": 2,
        }

        source_config = {
            "url": "http://feed",
            "name": "Fail Source",
            "category": "test",
            "credibility_score": 0.5,
        }

        processed = collector._process_article(raw_article, "src_fail", source_config)

        assert processed is not None, "Article discarded on enrichment error"

        enrichment = processed.article_metadata.enrichment
        assert enrichment.error == "API Error"
        assert enrichment.language == "en"  # Default fallback
        assert enrichment.model_version == "fallback_v1"
