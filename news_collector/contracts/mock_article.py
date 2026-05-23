from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import AnyHttpUrl, Field, TypeAdapter

from news_collector.contracts import CollectorArticleModel

_mock_url: AnyHttpUrl = TypeAdapter(AnyHttpUrl).validate_python(
    "https://example.com/mock-article"
)


class MockArticle(CollectorArticleModel):
    """
    Article model used for dry-run simulations and testing.
    Provides safe defaults for all fields.
    """

    id: int = 999999
    url: AnyHttpUrl = _mock_url
    title: str = "Mock Article for Simulation"
    summary: str = "This is a simulated article created during a dry-run or test."
    content: Optional[str] = (
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 50
    )
    source_id: str = "mock-source"
    source_name: str = "Mock Source"
    category: str = "general"
    published_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    authors: List[str] = ["Mock Author"]
    language: str = "en"
    word_count: int = 500
    reading_time_minutes: int = 5

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
