import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path.cwd()))

try:
    from news_collector.scoring.basic_scorer import BasicScorer
    from news_collector.storage.models import Article
    
    print("Initializing Scorer...")
    scorer = BasicScorer()
    
    # Test Case 1: Naive Collected Date
    print("\nTest 1: Naive Collected Date")
    article1 = Article(title="Test 1", collected_date=datetime.now()) # Naive
    try:
        s = scorer._calculate_recency_score(article1)
        print(f"Score: {s}")
    except Exception as e:
        print(f"FAIL: {e}")

    # Test Case 2: Naive Published Date
    print("\nTest 2: Naive Published Date")
    article2 = Article(title="Test 2", published_date=datetime.now()) # Naive
    try:
        s = scorer._calculate_recency_score(article2)
        print(f"Score: {s}")
    except Exception as e:
        print(f"FAIL: {e}")

except Exception as e:
    print(f"Global Error: {e}")
    import traceback
    traceback.print_exc()
