import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from news_collector.scoring.basic_scorer import BasicScorer

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"

# Setup logging
logging.basicConfig(level=logging.INFO)

async def test_async_scoring():
    print("🧪 Testing Async Scoring...")
    
    scorer = BasicScorer()
    
    # Dummy article data simulating what we pass in main.py
    article_data = {
        "article": {
            "id": "test-123",
            "title": "AsyncIO is great for concurrency",
            "summary": "This article discusses how async/await improves performance.",
            "url": "http://example.com/async",
            "published_date": None,
            "collected_date": datetime.now(timezone.utc),
            "article_metadata": {"credibility_score": 0.8},
            "peer_reviewed": True,
            "is_preprint": False,
            "doi": "10.1234/async",
            "journal": "Journal of Async",
        },
        "source_config": {"credibility_score": 0.9}
    }
    
    print("  • Starting score_article_async...")
    result = await scorer.score_article_async(article_data)
    
    print(f"  • Result keys: {list(result.keys())}")
    print(f"  • Final Score: {result.get('final_score')}")
    
    if result.get("final_score") is not None and result.get("success") is not False:
        print("✅ Async scoring successful!")
    else:
        print("❌ Async scoring failed or returned unexpected structure.")
        print(result)

if __name__ == "__main__":
    asyncio.run(test_async_scoring())
