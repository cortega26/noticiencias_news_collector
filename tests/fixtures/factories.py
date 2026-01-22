from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from news_collector.contracts import CollectorArticleModel
from news_collector.storage.models import Article

def create_article(
    id: str = "test_id",
    title: str = "Test Article Title", 
    url: str = "https://example.com/test",
    content: str = "This is a test article content." * 50,
    summary: str = "Test summary.",
    source_id: str = "test_source",
    published_date: Optional[datetime] = None,
    **kwargs
) -> Article:
    """Factory for Article domain model."""
    if published_date is None:
        published_date = datetime.now(timezone.utc)
        
    return Article(
        id=id,
        title=title,
        url=url,
        content=content,
        summary=summary,
        source_id=source_id,
        published_date=published_date,
        **kwargs
    )

def create_collector_article(
    title: str = "Test Collector Article",
    url: str = "https://example.com/collector",
    source_id: str = "test_source",
    **kwargs
) -> CollectorArticleModel:
    """Factory for CollectorArticleModel (Pydantic)."""
    defaults = {
        "title": title,
        "url": url,
        "source_id": source_id,
        "source_name": "Test Source",
        "category": "general",
        "published_date": datetime.now(timezone.utc),
        "content": "Content " * 100,
        "summary": "Summary " * 10,
        "word_count": 100,
        "reading_time_minutes": 1,
        "authors": ["Test Author"],
        "language": "en"
    }
    defaults.update(kwargs)
    return CollectorArticleModel(**defaults)
