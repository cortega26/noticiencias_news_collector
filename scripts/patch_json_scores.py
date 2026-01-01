
import json
import os
import sys
from datetime import datetime, timezone

# Add project root to path
sys.path.append(os.getcwd())

from news_collector.scoring.cognitive_scorer import CognitiveScorer

JSON_PATH = "data/exports/latest_articles.json"

class SimpleArticle:
    def __init__(self, data):
        self.id = data.get("id", 0)
        self.title = data.get("title", "")
        self.summary = data.get("summary", "")
        self.content = data.get("content", "") or self.summary 
        self.source_id = "test_source"
        self.published_date = datetime.now(timezone.utc)
        self.source_name = data.get("source_name", "Unknown")
        self.url = data.get("url", "")
        self.authors = data.get("authors", [])
        self.category = data.get("category", "general")
        self.word_count = len(self.content.split())
        self.content_quality_score = 0.5
        self.article_metadata = {}
        # Attributes required by BasicScorer
        self.peer_reviewed = False
        self.is_preprint = False
        self.journal = ""
        self.citations = 0
        self.doi = ""

def patch():
    if not os.path.exists(JSON_PATH):
        print(f"No JSON file found at {JSON_PATH}")
        return

    print("Loading JSON...")
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        articles = json.load(f)

    if not articles:
        print("No articles to patch.")
        return

    print("Initializing CognitiveScorer (llama3.2)...")
    scorer = CognitiveScorer()
    
    # Patch top 3 articles
    count = 0
    for i in range(len(articles)):
        if count >= 3: break
        
        art_data = articles[i]
        print(f"Scoring article {i+1}: {art_data.get('title', 'No Title')[:40]}...")
        
        art_obj = SimpleArticle(art_data)
        source_config = {"credibility_score": 0.8, "name": art_obj.source_name, "category": "general"}
        
        try:
            result = scorer.score_article(art_obj, source_config)
            
            new_score = result['final_score']
            engagement = result['components'].get('engagement', 0.0)
            
            print(f"  -> New Score: {new_score}")
            print(f"  -> Engagement: {engagement}")
            
            if engagement > 0.0:
                articles[i]["score"] = new_score
                articles[i]["final_score"] = new_score
                articles[i]["components"] = result["components"]
                # Mark as patched in title for visibility? No, user wants real data.
                count += 1
            else:
                 print("  -> Zero engagement returned (Still failing?)")
                 
        except Exception as e:
            print(f"  -> Failed: {e}")
            import traceback
            traceback.print_exc()

    print("Saving patched JSON...")
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(articles, f, indent=2, ensure_ascii=False)
    print("Done! Refresh Admin Panel.")

if __name__ == "__main__":
    patch()
