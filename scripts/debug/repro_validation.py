from datetime import datetime

from news_collector.contracts.collector import CollectorArticleModel
from news_collector.contracts.common import ArticleMetadataModel

try:
    naive = datetime(2023, 1, 1, 12, 0, 0)
    model = CollectorArticleModel(
        title="Valid Title length > 10",
        url="https://example.com/naive",
        source_id="source_id",
        source_name="Source Name",
        category="tech",
        published_date=naive,
        content="Long content " * 10,
        summary="Summary of enough length used to pass the validation check which enforces fifty chars.",
        word_count=100,
        reading_time_minutes=1,
        authors=["Test Author"],
        language="en",
        article_metadata=ArticleMetadataModel(
            credibility_score=0.8,
            original_url="https://example.com/naive",
            source_metadata={"foo": "bar"},
        ),
    )
    print("Success")
except Exception as e:
    print(f"Error: {e}")
