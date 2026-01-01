import sys
import os
import asyncio
import logging
from datetime import datetime, timezone

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from news_collector.storage.models import Article
from news_collector.scoring.cognitive_scorer import CognitiveScorer
from news_collector.utils.llm_client import LLMClient

# Setup logging
logging.basicConfig(level=logging.INFO)

class MockLLMClient(LLMClient):
    """Mock LLM to avoid needing a real Ollama instance for basic testing."""
    def generate(self, prompt, system=None, format="json"):
        print(f"\n[MockLLM] Prompt: {prompt[:50]}...")
        print(f"[MockLLM] System: {system[:50]}...")
        
        # Determine if it's the score request
        if "0-5" in system:
            return {
                "scores": {
                    "contraintuitivo": 4,
                    "impacto_humano": 5,
                    "conflicto_ideas": 3,
                    "incertidumbre": 2,
                    "utilidad_practica": 4
                },
                "reasoning": "Mock reasoning: High impact and utility."
            }
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
        collected_date=datetime.now(timezone.utc)
    )
    
    # Initialize Scorer with Mock LLM
    scorer = CognitiveScorer(llm_client=MockLLMClient())
    
    # Run Score
    result = scorer.score_article(article)
    
    print("\nScore Result:")
    print(f"Final Score: {result['final_score']}")
    print(f"Decision: {result['decision_label']}")
    print("Components:")
    for k, v in result['components'].items():
        print(f"  - {k}: {v}")
        
    print("\nCognitive Details:")
    print(result['cognitive_details'])
    
    # Verify Math
    # Cognitive: (4+5+3+2+4)/5 = 3.6/5 => 72% => 0.72 normalized?
    # Wait, 18/5 = 3.6. 3.6 * 0.20 = 0.72? No.
    # Logic in code: sum(values) * 0.20 -> 18 * 0.20 = 3.6 (Raw)
    # Norm: 3.6 / 5.0 = 0.72.
    # Source (mock default/calc): likely ~0.3-0.5 depending on defaults.
    # Recency: ~0.05 if no date.
    # Content: ~0.5.
    # Final = weights calculation.
    
    assert result['components']['cognitive_engagement_norm'] == 0.72
    print("\nValidation PASSED for Cognitive Component.")

if __name__ == "__main__":
    asyncio.run(main())
