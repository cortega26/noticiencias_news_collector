import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from news_collector.infrastructure.llm.provider import OllamaProvider
from news_collector.scoring.cognitive_scorer import CognitiveScorer
from news_collector.storage.models import Article

# Setup logging
logging.basicConfig(level=logging.INFO)


class MockOllamaProvider(OllamaProvider):
    """Mock LLM to avoid needing a real Ollama instance for basic testing."""

    async def generate_async(self, prompt, system=None, json_mode=False):
        print(f"\n[MockLLM] Prompt: {prompt[:50]}...")
        print(f"[MockLLM] System: {system[:50]}...")

        # Determine if it's the score request
        if "0-5" in system:
            return {
                "results": [
                    {
                        "item_index": 1,
                        "scores": {
                            "substance": 4,
                            "narrative": 5,
                            "relevance": 3,
                            "credibility": 4,
                        },
                        "reasoning": "Mock reasoning: High impact and utility.",
                    }
                ]
            }
        return {}

    def generate_sync(self, prompt, system=None, json_mode=False, stream=False):
        # Sync version not used by batch scorer but implemented for safety
        return {}


async def main():
    print("Testing Cognitive Scorer...")

    # Create article
    article = Article(
        id="test-1",
        title="New Study Reveals Coffee Reverses Aging in Mice",
        summary="A new study from Harvard shows that coffee consumption extends life in mice by 20%.",
        content="Full content here... details about telomeres and antioxidants...",
        url="http://example.com",
        published_date=datetime.now(timezone.utc),
        collected_date=datetime.now(timezone.utc),
    )

    # Initialize Scorer with Mock LLM
    scorer = CognitiveScorer(llm_client=MockOllamaProvider())

    # Run Score
    result = scorer.score_article(article)

    print("\nScore Result:")
    print(f"Final Score: {result['final_score']}")
    print(f"Decision: {result['decision_label']}")
    print("Components:")
    for k, v in result["components"].items():
        print(f"  - {k}: {v}")

    print("\nCognitive Details:")
    print(result["cognitive_details"])

    # Verify Math
    # Verify Math
    # NQI = (4*0.35 + 5*0.30 + 3*0.20 + 4*0.15) / 5.0
    # = (1.4 + 1.5 + 0.6 + 0.6) / 5.0
    # = 4.1 / 5.0 = 0.82

    # Check components
    nqi_substance = result["components"]["nqi_substance"]
    # 4/5 = 0.8
    assert nqi_substance == 0.8

    # Overall NQI is not directly stored as one field but blended into final score
    print("\nValidation PASSED for Cognitive Component.")


if __name__ == "__main__":
    asyncio.run(main())
