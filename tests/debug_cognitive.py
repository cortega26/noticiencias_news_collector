
import logging
import sys
import os
from datetime import datetime, timezone

# Configure logging
logging.basicConfig(level=logging.INFO)

# Mock Source Config
class MockSourceConfig(dict):
    pass

# Mock Article
class MockArticle:
    def __init__(self):
        self.id = 1
        self.title = "Breakthrough in Nuclear Fusion"
        self.summary = "Scientists achieve net energy gain in fusion reaction."
        self.content = "Researchers at the National Ignition Facility have successfully produced more energy from fusion than was used to drive it."
        self.source_id = "test_source"
        self.published_date = datetime.now(timezone.utc)
        self.source_name = "Tests"
        self.url = "http://test.com"
        self.authors = []
        self.category = "science"
        # Attributes required by BasicScorer
        self.word_count = 1000
        self.content_quality_score = 0.8

try:
    from news_collector.scoring.cognitive_scorer import CognitiveScorer
    
    print("Initializing CognitiveScorer...", flush=True)
    scorer = CognitiveScorer()
    
    print("\n--- Testing Internal LLM Method directly ---", flush=True)
    article = MockArticle()
    try:
        cog_result = scorer._calculate_cognitive_engagement(article)
        print(f"Direct Method Result: {cog_result}", flush=True)
    except Exception as e:
        print(f"Direct Method Failed: {e}", flush=True)
        import traceback
        traceback.print_exc()

except Exception as e:
    print(f"❌ Critical Error: {e}", flush=True)
    import traceback
    traceback.print_exc()
