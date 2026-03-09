from news_collector.contracts.adapters import adapt_export_article_to_collector_payload
from news_collector.contracts.collector import CollectorArticleModel

sample_export = {
    "id": 123,
    "url": "https://example.com/test",
    "title": "A Valid Long Enough Title for Testing",
    "summary": "This is a summary of the article",
    "published_date": "2023-10-10T10:00:00Z",
    "source_name": "Test Source",
    "source_id": "test_script",
    "category": "science",
    "metadata": {
        "original_url": "https://example.com/test"
    }
}

adapted = adapt_export_article_to_collector_payload(sample_export)
print("Adapted:", adapted)

try:
    model = CollectorArticleModel.model_validate(adapted)
    print("Validated successfully!")
except Exception as e:
    print("Validation Error:", e)

