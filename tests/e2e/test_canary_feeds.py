import sys
from pathlib import Path
from typing import Tuple, Optional
import pytest
from news_collector.collectors import RSSCollector
from news_collector.storage import models as storage_models
from news_collector.storage.database import DatabaseManager

# Fixture setup similar to other e2e tests
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

@pytest.fixture
def isolated_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_path = tmp_path / "canary.db"
    manager = DatabaseManager({"type": "sqlite", "path": db_path})
    
    import news_collector.storage.database as database_module
    monkeypatch.setattr(database_module, "_db_manager", manager, raising=False)
    monkeypatch.setattr("news_collector.collectors.rss_collector.get_database_manager", lambda: manager)
    
    try:
        yield manager
    finally:
        manager.close()

def test_canary_rss_parsing(isolated_database, monkeypatch):
    """
    Canary test:
    1. Reads `tests/data/canary_rss.xml`.
    2. Runs RSSCollector against it.
    3. Verifies strictly the output in DB.
    """
    
    # helper to mock _fetch_feed
    def mock_fetch_feed(self, source_id: str, feed_url: str) -> Tuple[Optional[str], Optional[int]]:
        with (DATA_DIR / "canary_rss.xml").open("r", encoding="utf-8") as f:
            return f.read(), 200

    collector = RSSCollector()
    
    # Mock network & rate limits
    monkeypatch.setattr(RSSCollector, "_respect_robots", lambda self, url: (True, None))
    monkeypatch.setattr(RSSCollector, "_enforce_domain_rate_limit", lambda *args: None)
    monkeypatch.setattr(RSSCollector, "_fetch_feed", mock_fetch_feed)
    
    # Mock _save_article to avoid full enrichment pipeline if needed, 
    # BUT we want E2E, so we rely on isolated_database.
    # However, enrichment might try to call LLMs etc. 
    # We should probably mock enrichment if it makes network calls. 
    # checking rss_collector.py: _process_article calls enrichment_pipeline.run_pipeline
    # We should mock enrichment_pipeline.run_pipeline to be safe/fast/deterministic.
    
    def mock_enrichment(article):
        # Return minimal enrichment to pass. 
        # The real pipeline returns a dict of enrichment data.
        return {
            "language": "en",
            "sentiment": "neutral",
            "topics": ["canary"],
            "entities": ["Test"],
            "model_version": "mock-v1",
            "normalized_title": "mock title",
            "normalized_summary": "mock summary"
        }
        
    monkeypatch.setattr("news_collector.collectors.rss_collector.enrichment_pipeline.enrich_article", mock_enrichment)

    # Run collection
    source_config = {
        "name": "Canary Source",
        "url": "https://noticiencias.com/canary",
        "category": "science",
        "credibility_score": 1.0, 
        "language": "en"
    }
    
    stats = collector.collect_from_source("canary_test", source_config)
    
    assert stats["success"] is True
    assert stats["articles_found"] == 2
    # articles_saved might be less if validation fails, but our canary data should pass.
    # The second article has HTML in description but content is sufficient.
    
    # Verify DB content
    with isolated_database.get_session() as session:
        articles = session.query(storage_models.Article).order_by(storage_models.Article.url).all()
        assert len(articles) == 2
        
        # Check Article 1
        art1 = articles[0]
        assert "Valid Article" in art1.title
        assert "Jane Doe" in art1.authors
        assert art1.category == "science"
        # RSSCollector maps content to summary
        assert "content of article 1" in art1.summary
        
        # Check Article 2
        art2 = articles[1]
        assert "Messy HTML" in art2.title
        # RSSCollector preferred the longer content over the description 
        assert "content has structure" in art2.summary 
        assert "<b>" not in art2.summary # Should be cleaned
        assert "alert(" not in art2.summary # Script stripped
        assert len(art2.authors) == 2 # Dr. Smith, Prof. Jones
