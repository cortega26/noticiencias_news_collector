import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime, timezone
# Mocking sqlite3 connection for tests to avoid disk I/O dependency in unit tests?
# The code uses sqlite3.connect(CACHE_DB_PATH). We can patch sqlite3. 
# But for now let's just use the file or an in-memory db path if we could inject it.
# CognitiveScorer hardcodes the path. I'll mock `_init_cache` and `_get_from_cache`/`_save_to_cache` as done in the previous attempt.

from news_collector.scoring.cognitive_scorer import CognitiveScorer
from news_collector.storage.models import Article

@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.is_healthy = True # Attribute, not method call in some contexts, but let's set both
    llm.is_healthy_async = AsyncMock(return_value=True) 
    
    # CognitiveScorer checks self.is_llm_healthy boolean usually.
    
    llm.generate_async = AsyncMock(return_value={
        "results": [
            {
                "item_index": 1,
                "scores": {
                    "substance": 4, 
                    "narrative": 5, 
                    "relevance": 3, 
                    "credibility": 4
                },
                "reasoning": "Mocked Reasoning"
            }
        ]
    })
    return llm

@pytest.fixture
def sample_article():
    return Article(
        id="test_1",
        title="Breakthrough in Quantum Computing",
        summary="Scientists discover new qubit state.",
        content="Full content about quantum physics... " * 50,
        url="http://test.com/1",
        source_id="test_source",
        published_date=datetime.now(timezone.utc)
    )

def test_batch_scoring_happy_path(mock_llm, sample_article):
    async def run_test():
        # Initialize scorer
        scorer = CognitiveScorer(llm_client=mock_llm)
        
        # Enforce healthy state
        scorer.is_llm_healthy = True
        
        # Mock Cache to return None (Miss)
        scorer._get_from_cache = MagicMock(return_value=None)
        scorer._save_to_cache = MagicMock()
        
        payloads = [{"article": {
            "title": sample_article.title, 
            "url": sample_article.url, 
            "summary": sample_article.summary, 
            "content": sample_article.content,
            "published_date": sample_article.published_date.isoformat()
        }, "source_config": {"url": "http://test.com"}}]
        
        results = await scorer.score_batch_async(payloads)
        
        assert len(results) == 1
        comp = results[0]["components"]
        
        # Check NQI keys (normalized 0-1)
        # Substance 4/5 = 0.8
        # Narrative 5/5 = 1.0
        assert comp["nqi_substance"] == 0.8
        assert comp["engagement_potential"] == 1.0 # Mapped from narrative
        
        assert results[0]["cognitive_details"]["reasoning"] == "Mocked Reasoning"

    asyncio.run(run_test())

def test_heuristic_fallback_when_llm_unhealthy(mock_llm, sample_article):
    async def run_test():
        scorer = CognitiveScorer(llm_client=mock_llm)
        scorer.is_llm_healthy = False # Simulate unhealthy
        scorer._get_from_cache = MagicMock(return_value=None)
        
        payloads = [{"article": {"title": sample_article.title, "url": sample_article.url}}]
        
        results = await scorer.score_batch_async(payloads)
        
        assert len(results) == 1
        details = results[0]["cognitive_details"]
        assert details.get("heuristic") is True
        assert "Heuristic" in results[0]["explanation"]["reasoning"]
    
    asyncio.run(run_test())

def test_cache_hit_skips_llm(mock_llm, sample_article):
    async def run_test():
        scorer = CognitiveScorer(llm_client=mock_llm)
        
        # Mock cache hit
        cached_val = {
            "score": 0.9, 
            "details": {
                "substance": 4.5, 
                "narrative": 4.5,
                "relevance": 4.5,
                "credibility": 4.5
            }, 
            "reasoning": "Old cache (Cached)"
        }
        scorer._get_from_cache = MagicMock(return_value=cached_val)
        
        payloads = [{"article": {"title": sample_article.title, "url": sample_article.url}}]
        
        # Run
        results = await scorer.score_batch_async(payloads)
        
        # Assert
        # Cached score = 0.9
        # In finalize_score, if cache hit, we often reuse dimensions if available or calculate.
        # But wait, finalize_score expects details to have standard keys optionally.
        # If details has substance/narrative, they are used.
        # 4.5/5.0 = 0.9
        
        assert results[0]["final_score"] > 0.8 # logic uses cache score + hybrid components
        # Actually logic: final_score calculation re-runs in finalize_score based on components.
        # Check CognitiveScorer._finalize_score lines 332-340 for Heuristic vs 340+ for LLM.
        # If cached, it calls _finalize_score passing cached dict as 'cognitive_res'.
        # 'is_heuristic' defaults False.
        # So it tries to parse details.
        
        assert "Cached" in results[0]["explanation"]["reasoning"] 
        # Ensure LLM generate was NOT called
        mock_llm.generate_async.assert_not_called()
    
    asyncio.run(run_test())
