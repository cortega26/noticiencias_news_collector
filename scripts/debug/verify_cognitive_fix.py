import asyncio
from datetime import datetime, timezone

from news_collector.scoring.cognitive_scorer import CognitiveScorer


async def test_cognitive_fix():
    print("--- Testing CognitiveScorer Fix ---")

    # 1. Initialize
    try:
        scorer = CognitiveScorer()
        print(
            f"✅ CognitiveScorer initialized. Weights keys: {list(scorer.weights.keys())}"
        )

        if "engagement_potential" not in scorer.weights:
            print("❌ FAIL: 'engagement_potential' missing from weights!")
            return
        else:
            print("✅ 'engagement_potential' is present.")

    except Exception as e:
        print(f"❌ FAIL: Initialization crashed: {e}")
        return

    # 2. Test Scoring (Batch)
    article = {
        "title": "Test Article regarding Science",
        "summary": "This is a test summary about science data.",
        "content": "Data 2026. p-value < 0.05. Significant results found in LatAm study.",
        "url": "http://test.com/1",
        "source_id": "test_source",
        "published_date": datetime.now(timezone.utc).isoformat(),
    }

    payloads = [{"article": article, "source_config": {"name": "Test Source"}}]

    try:
        print("\nRunning score_batch_async...")
        results = await scorer.score_batch_async(payloads)

        if not results:
            print("❌ FAIL: Empty results returned.")
        else:
            res = results[0]
            print(f"✅ Result obtained. Final Score: {res.get('final_score')}")
            print(f"   Components: {res.get('components')}")

            if res.get("decision_label") == "error":
                print("⚠️ Result indicates error/fallback used.")

    except Exception as e:
        print(f"❌ FAIL: score_batch_async crashed: {e}")


if __name__ == "__main__":
    asyncio.run(test_cognitive_fix())
