import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
# Mocking sqlite3 connection for tests to avoid disk I/O dependency in unit tests?
# The code uses sqlite3.connect(CACHE_DB_PATH). We can patch sqlite3. 
# But for now let's just use the file or an in-memory db path if we could inject it.
# CognitiveScorer hardcodes the path. I'll mock `_init_cache` and `_get_from_cache`/`_save_to_cache` as done in the previous attempt.

from news_collector.scoring.cognitive_scorer import CognitiveScorer
from news_collector.storage.models import Article

@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.is_healthy.return_value = True
    llm.generate.return_value = {
        "results": [
            {
                "item_index": 1,
                "scores": {"contraintuitivo": 4, "impacto_humano": 5, "conflicto_ideas": 3, "incertidumbre": 2, "utilidad_practica": 4},
                "reasoning": "Mocked Reasoning"
            }
        ]
    }
    return llm

@pytest.fixture
def sample_article():
    return Article(
        id="test_1",
        title="Breakthrough in Quantum Computing",
        summary="Scientists discover new qubit state.",
        content="Full content about quantum physics... " * 50,
        url="http://test.com/1",
        source_id="test_source"
    )

def test_batch_scoring_happy_path(mock_llm, sample_article):
    async def run_test():
        scorer = CognitiveScorer(llm_client=mock_llm)
        scorer._get_from_cache = MagicMock(return_value=None)
        scorer._save_to_cache = MagicMock()
        
        payloads = [{"article": {"title": sample_article.title, "url": sample_article.url, "summary": sample_article.summary, "content": sample_article.content}}]
        
        results = await scorer.score_batch_async(payloads)
        
        assert len(results) == 1
        comp = results[0]["components"]
        assert comp["cognitive_engagement_raw"] == 3.6
        assert comp["engagement"] == 0.72
        assert results[0]["cognitive_details"]["reasoning"] == "Mocked Reasoning"

    asyncio.run(run_test())

def test_heuristic_fallback_when_llm_unhealthy(mock_llm, sample_article):
    async def run_test():
        mock_llm.is_healthy.return_value = False
        scorer = CognitiveScorer(llm_client=mock_llm)
        scorer._get_from_cache = MagicMock(return_value=None)
        # Note: we need to ensure is_llm_healthy state is updated or checked.
        # scorer calls is_healthy in constructor? No, in reset_cycle_metrics/check_budget.
        # But score_batch_async calls check_budget too.
        # However, check_budget uses self.is_llm_healthy which is init to True.
        # score_batch_async logic: "use_llm = self._check_budget()".
        # _check_budget returns "if not self.is_llm_healthy: return False".
        # So we must set scorer.is_llm_healthy = False manually or mock check_budget.
        scorer.is_llm_healthy = False
        
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
        # Note: In real code, _get_from_cache appends " (Cached)" to reasoning.
        # Since we mock it, we must match expected behavior or just assert what we return.
        # Also, reasoning is expected inside 'details' for explanation generation.
        cached_val = {
            "score": 0.9, 
            "details": {"cached": True, "reasoning": "Old cache (Cached)"}, 
            "reasoning": "Old cache (Cached)"
        }
        scorer._get_from_cache = MagicMock(return_value=cached_val)
        
        payloads = [{"article": {"title": sample_article.title, "url": sample_article.url}}]
        
        # Run
        results = await scorer.score_batch_async(payloads)
        
        # Assert
        assert results[0]["components"]["engagement"] == 0.9
        assert "Cached" in results[0]["explanation"]["reasoning"] 
        # Ensure LLM generate was NOT called
        mock_llm.generate.assert_not_called()
    
    asyncio.run(run_test())
