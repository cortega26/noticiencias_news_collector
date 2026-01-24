from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from news_collector.contracts import CollectorArticleModel


class MockArticle(CollectorArticleModel):
    """
    Article model used for dry-run simulations and testing.
    Provides safe defaults for all fields.
    """
    
    id: int = 999999
    url: str = "https://example.com/mock-article"
    title: str = "Mock Article for Simulation"
    summary: str = "This is a simulated article created during a dry-run or test."
    content: Optional[str] = "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
    source_id: str = "mock-source"
    source_name: str = "Mock Source"
    category: str = "general"
    published_date: datetime = datetime.now(timezone.utc)
    authors: List[str] = ["Mock Author"]
    language: str = "en"
    score: float = 0.5
    
    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
