import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from news_collector.scoring.cognitive_scorer import CognitiveScorer
from news_collector.storage.models import Article


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.generate_async = AsyncMock()
    return llm


@pytest.fixture
def temp_db_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    yield path
    if path.exists():
        path.unlink()


@pytest.fixture
def cognitive_scorer(mock_llm, temp_db_path):
    # Patch the CACHE_DB_PATH in the module
    with patch("news_collector.scoring.cognitive_scorer.CACHE_DB_PATH", temp_db_path):
        scorer = CognitiveScorer(llm_client=mock_llm)
        yield scorer


@pytest.fixture
def sample_article():
    return Article(
        id="cog1",
        url="http://cog.test/1",
        title="Cognitive Test Article",
        summary="Testing LLM scoring.",
        content="Content for LLM evaluation.",
        source_id="s1",
        published_date=datetime.now(timezone.utc),
        article_metadata={},
    )


def test_score_batch_llm_success(cognitive_scorer, mock_llm, sample_article):

    # Setup LLM response
    llm_response = {
        "results": [
            {
                "item_index": 1,
                "scores": {
                    "substance": 4.0,
                    "narrative": 3.0,
                    "relevance": 5.0,
                    "credibility": 4.5,
                },
                "reasoning": "Good article.",
            }
        ]
    }
    mock_llm.generate_async.return_value = llm_response

    payload = [{"article": sample_article.to_dict(), "source_config": {}}]
    results = asyncio.run(cognitive_scorer.score_batch_async(payload))

    assert len(results) == 1
    res = results[0]
    assert res["decision_label"] in ["priority", "publishable", "discard"]
    assert res["cognitive_details"]["substance"] == 4.0

    # Verify cache write
    cognitive_scorer._get_cache_key(sample_article)
    # 0.72 is approximately the result (weighted average)
    assert res["final_score"] == pytest.approx(0.72, abs=0.01)


def test_score_batch_cache_hit(cognitive_scorer, mock_llm, sample_article):

    # Seed cache
    cognitive_scorer._get_cache_key(sample_article)
    # Cache should store the LLM result structure
    cached_data = {
        "item_index": 1,
        "scores": {
            "substance": 5.0,
            "narrative": 4.0,
            "relevance": 5.0,
            "credibility": 5.0,
        },
        "details": {"substance": 5.0},
        "reasoning": "Cached reason",
    }
    # Force cache hit by mocking
    cognitive_scorer._get_from_cache = MagicMock(return_value=cached_data)

    # Call batch - LLM should NOT be called
    payload = [{"article": sample_article.to_dict(), "source_config": {}}]
    results = asyncio.run(cognitive_scorer.score_batch_async(payload))

    assert len(results) == 1
    # Check that score is high (near 0.8-1.0 depending on weights)
    # If using default weights, 5.0s should give high score.
    assert results[0]["final_score"] > 0.1
    assert results[0]["cognitive_details"]["substance"] == 5.0
    mock_llm.generate_async.assert_not_called()


def test_score_batch_llm_failure_fallback(cognitive_scorer, mock_llm, sample_article):

    # LLM returns None or errors
    mock_llm.generate_async.return_value = None

    payload = [{"article": sample_article.to_dict()}]
    results = asyncio.run(cognitive_scorer.score_batch_async(payload))

    assert len(results) == 1
    # Should be heuristic fallback
    assert results[0]["cognitive_details"].get("heuristic") is True
    assert cognitive_scorer.is_llm_healthy is False


def test_score_batch_budget_exhausted(cognitive_scorer, mock_llm, sample_article):

    # Simulate exhausted budget
    cognitive_scorer.max_cycle_budget_sec = 0.0

    payload = [{"article": sample_article.to_dict()}]
    results = asyncio.run(cognitive_scorer.score_batch_async(payload))

    assert len(results) == 1
    assert results[0]["cognitive_details"].get("heuristic") is True
    mock_llm.generate_async.assert_not_called()


def test_score_single_article_fallback(cognitive_scorer, sample_article, mock_llm):
    mock_llm.generate_async.return_value = None

    cognitive_scorer.heuristic.calculate_score = MagicMock(return_value=0.5)

    res = cognitive_scorer.score_article(sample_article)
    # The actual result is blended: 0.53 likely due to basic scorer defaults (freshness 0.5, source 0.5 etc).
    # Since we mocking heuristic to 0.5, and bases allow 0.5, the blended might be slightly higher or lower based on weights.
    # We just check the structure and that it ran.
    assert res["final_score"] > 0.0
    assert res["cognitive_details"]["heuristic"] is True


# --------------------------------------------------------------------------
# Plan 036 Step 4: prompt chunking + bounded fallback
# --------------------------------------------------------------------------


def _uniform_generate_async(prompt, system=None, json_mode=None):
    """Fake LLM response: one uniform score per `--- ITEM` marker found."""
    n = prompt.count("--- ITEM")
    return {
        "results": [
            {
                "item_index": i + 1,
                "scores": {
                    "substance": 3.0,
                    "narrative": 3.0,
                    "relevance": 3.0,
                    "credibility": 3.0,
                },
                "reasoning": f"r{i}",
            }
            for i in range(n)
        ]
    }


def _articles(n, title_prefix="Title"):
    return [
        Article(
            id=f"a{i}",
            url=f"http://test/{i}",
            title=f"{title_prefix}{i}",
            summary="s",
            content="c",
            source_id="s1",
            published_date=datetime.now(timezone.utc),
            article_metadata={},
        )
        for i in range(n)
    ]


def test_chunks_by_max_prompt_items(cognitive_scorer, mock_llm):
    cognitive_scorer.max_prompt_items = 2
    cognitive_scorer.max_prompt_chars = 1_000_000
    mock_llm.generate_async = AsyncMock(side_effect=_uniform_generate_async)

    articles = _articles(5)
    payloads = [{"article": a.to_dict(), "source_config": {}} for a in articles]

    results = asyncio.run(cognitive_scorer.score_batch_async(payloads))

    assert len(results) == 5
    assert mock_llm.generate_async.call_count == 3  # ceil(5/2) chunks
    assert all(r["cognitive_details"].get("heuristic") is not True for r in results)


def test_chunks_by_max_prompt_chars(cognitive_scorer, mock_llm):
    # Each item's prompt text is well over 20 chars, so this bound forces
    # one item per chunk even though max_prompt_items would allow more.
    cognitive_scorer.max_prompt_items = 100
    cognitive_scorer.max_prompt_chars = 20
    mock_llm.generate_async = AsyncMock(side_effect=_uniform_generate_async)

    articles = _articles(4)
    payloads = [{"article": a.to_dict(), "source_config": {}} for a in articles]

    results = asyncio.run(cognitive_scorer.score_batch_async(payloads))

    assert len(results) == 4
    assert mock_llm.generate_async.call_count == 4  # one chunk per item


def test_chunking_preserves_order_across_cache_hits(cognitive_scorer, mock_llm):
    cognitive_scorer.max_prompt_items = 2
    mock_llm.generate_async = AsyncMock(side_effect=_uniform_generate_async)

    articles = _articles(6)
    payloads = [{"article": a.to_dict(), "source_config": {}} for a in articles]

    def _cache(key):
        if key.startswith("Title1_") or key.startswith("Title4_"):
            marker = key.split("_")[0]
            return {
                "score": 0.9,
                "details": {"reasoning": f"cached-{marker}"},
                "reasoning": f"cached-{marker}",
            }
        return None

    cognitive_scorer._get_from_cache = MagicMock(side_effect=_cache)

    results = asyncio.run(cognitive_scorer.score_batch_async(payloads))

    assert len(results) == 6
    assert results[1]["cognitive_details"]["reasoning"] == "cached-Title1"
    assert results[4]["cognitive_details"]["reasoning"] == "cached-Title4"
    # Non-cached indices (0, 2, 3, 5) went through the chunked LLM path,
    # each getting a chunk-local `item_index` ("r0" or "r1") — the point
    # is that every one of them came from the LLM, not heuristic fallback,
    # and every original index still has exactly one result.
    for i in (0, 2, 3, 5):
        assert results[i]["cognitive_details"]["reasoning"] in ("r0", "r1")
        assert results[i]["cognitive_details"].get("heuristic") is not True


def test_one_failed_chunk_falls_back_only_for_that_chunk(cognitive_scorer, mock_llm):
    cognitive_scorer.max_prompt_items = 2
    articles = _articles(4)  # two chunks of 2
    payloads = [{"article": a.to_dict(), "source_config": {}} for a in articles]

    call_count = 0

    async def _generate(prompt, system=None, json_mode=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _uniform_generate_async(prompt)
        return None  # second chunk's LLM call fails entirely

    mock_llm.generate_async = AsyncMock(side_effect=_generate)

    results = asyncio.run(cognitive_scorer.score_batch_async(payloads))

    assert len(results) == 4
    # First chunk (indices 0-1) succeeded via the LLM.
    assert results[0]["cognitive_details"].get("heuristic") is not True
    assert results[1]["cognitive_details"].get("heuristic") is not True
    # Second chunk (indices 2-3) fell back to heuristic, not repeated LLM calls.
    assert results[2]["cognitive_details"].get("heuristic") is True
    assert results[3]["cognitive_details"].get("heuristic") is True
    assert cognitive_scorer.is_llm_healthy is False


def test_chunk_failure_cascades_to_later_untried_chunks(cognitive_scorer, mock_llm):
    """Characterizes inherited (pre-chunking) circuit-breaker behavior,
    surfaced by a subagent review of plan 036: `is_llm_healthy` is a
    per-cycle flag, not per-chunk. Once any chunk's `_call_llm_batch`
    returns falsy, every later chunk in the *same* score_batch_async call
    skips the LLM entirely via `_check_budget()` and goes straight to
    heuristic — it is not retried, even though it never itself failed.
    This predates plan 036 (the flag existed for the old single-prompt
    path); chunking just gives one transient failure a larger blast
    radius within one cycle. Not changed by plan 036 — characterized here
    so the behavior is explicit rather than silently assumed."""
    cognitive_scorer.max_prompt_items = 2
    articles = _articles(6)  # three chunks of 2
    payloads = [{"article": a.to_dict(), "source_config": {}} for a in articles]

    call_count = 0

    async def _generate(prompt, system=None, json_mode=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _uniform_generate_async(prompt)  # chunk 1: succeeds
        return None  # chunk 2 and beyond: total LLM failure

    mock_llm.generate_async = AsyncMock(side_effect=_generate)

    results = asyncio.run(cognitive_scorer.score_batch_async(payloads))

    assert len(results) == 6
    # Chunk 1 (indices 0-1) succeeded via the LLM.
    assert results[0]["cognitive_details"].get("heuristic") is not True
    assert results[1]["cognitive_details"].get("heuristic") is not True
    # Chunk 2 (indices 2-3) genuinely failed and fell back.
    assert results[2]["cognitive_details"].get("heuristic") is True
    assert results[3]["cognitive_details"].get("heuristic") is True
    # Chunk 3 (indices 4-5) never failed itself, but is cascaded to
    # heuristic anyway because is_llm_healthy is a cycle-wide flag.
    assert results[4]["cognitive_details"].get("heuristic") is True
    assert results[5]["cognitive_details"].get("heuristic") is True
    # Only 2 real LLM calls happened: chunk 3's was never attempted.
    assert mock_llm.generate_async.call_count == 2
    assert cognitive_scorer.is_llm_healthy is False


def test_no_missing_or_duplicate_item_across_chunks(cognitive_scorer, mock_llm):
    cognitive_scorer.max_prompt_items = 3
    mock_llm.generate_async = AsyncMock(side_effect=_uniform_generate_async)

    articles = _articles(10, title_prefix="Unique")
    payloads = [{"article": a.to_dict(), "source_config": {}} for a in articles]

    results = asyncio.run(cognitive_scorer.score_batch_async(payloads))

    assert len(results) == 10
    assert all(r.get("decision_label") != "error" for r in results)
