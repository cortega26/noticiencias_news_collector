from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from news_collector.storage.models import Article
from news_collector.system import NewsCollectorSystem


@pytest.fixture
def mock_system_components():
    """Setup a system with mocked dependencies for scoring."""
    system = NewsCollectorSystem()
    system.db_manager = MagicMock()
    system.scorer = AsyncMock()
    # Explicitly mock reset_cycle_metrics as SYNC to match production usage and avoid RuntimeWarning
    system.scorer.reset_cycle_metrics = MagicMock()
    system.logger = MagicMock()

    # Mock logger to accept log calls
    system.logger.create_module_logger.return_value = MagicMock()

    return system


@pytest.fixture
def sample_pending_articles():
    """Create 3 sample articles for scoring."""
    articles = []
    for i in range(3):
        article = Article(
            id=i + 1,
            title=f"Article {i+1}",
            summary=f"Summary {i+1}",
            url=f"http://example.com/{i+1}",
            content="Content",
            source_id="news_source",
            processing_status="pending",
            collected_date=datetime.now(timezone.utc),
            published_date=datetime.now(timezone.utc),
            word_count=100,
            duplication_confidence=0.0,
        )
        articles.append(article)
    return articles


@pytest.mark.asyncio
async def test_scoring_fail_all_behavior(
    mock_system_components, sample_pending_articles
):
    """
    Test that currently (before fix) a batch failure causes all items to fail,
    and after fix, it recovers.
    """
    system = mock_system_components
    articles = sample_pending_articles

    # Setup DB to return these articles
    system.db_manager.get_pending_articles.return_value = articles

    # Setup Scorer to support batching BUT fail during batch
    system.scorer.score_batch_async = AsyncMock(
        side_effect=Exception("Batch LLM Timeout")
    )

    # Setup Scorer to support individual scoring (Legacy/Fallback)
    # Item 1: Success
    # Item 2: Fail (Simulating individual error)
    # Item 3: Success

    async def mock_score_single(payload):
        # NOTE: adapt_to_scoring_input returns ScoringInputModel which has 'article' field
        if "Article 2" in payload["article"]["title"]:
            raise Exception("Single Item Error")
        return {"final_score": 0.9, "should_include": True, "components": {}}

    system.scorer.score_article_async = AsyncMock(side_effect=mock_score_single)

    # Execute
    # We expect the system to TRY batch, FAIL, LOG, and then FALLBACK to sequential
    # We expect the system to TRY batch, FAIL, LOG, and then FALLBACK to sequential
    _ = await system._execute_scoring({"source_details": {}}, dry_run=False)

    # Assertions
    bulk_calls = system.db_manager.update_articles_score_bulk.call_args_list

    # Bulk update should be called exactly once
    assert len(bulk_calls) == 1, "Expected one bulk update call"

    # Verify fallback happened
    # Batch should have been called once
    system.scorer.score_batch_async.assert_called_once()

    # Check if get_pending_articles was called
    system.db_manager.get_pending_articles.assert_called_once()

    # Single score should have been called 3 times (fallback)
    assert (
        system.scorer.score_article_async.call_count == 3
    ), f"Fallback to sequential didn't happen. Count: {system.scorer.score_article_async.call_count}"

    # Extract the payload passed to the bulk update
    bulk_payload = bulk_calls[0][0][0]  # The first positional argument
    updated_ids = [item[0] for item in bulk_payload]

    # STRICT ASSERTION: Only 2 successful updates (Article 1 and 3)
    assert (
        len(updated_ids) == 2
    ), f"Expected 2 successful scores, got {len(updated_ids)}"

    # Verify EXACTLY which articles were updated (1 and 3)
    assert 1 in updated_ids
    assert 3 in updated_ids
    assert (
        2 not in updated_ids
    ), "Article 2 should have failed silently/logged error but NOT updated DB score"


@pytest.mark.asyncio
async def test_scoring_fallback_missing_safety(
    mock_system_components, sample_pending_articles
):
    """
    Test that if fallback method is missing, we raise the original exception
    instead of failing silently or crashing with AttributeError.
    """
    system = mock_system_components
    articles = sample_pending_articles
    system.db_manager.get_pending_articles.return_value = articles

    # Batch fails
    batch_error = Exception("Batch Fatal")
    system.scorer.score_batch_async = AsyncMock(side_effect=batch_error)

    # Crucial: Fallback method is MISSING
    del system.scorer.score_article_async

    # Execute
    with pytest.raises(Exception) as excinfo:
        await system._execute_scoring({"source_details": {}}, dry_run=False)

    assert "Batch Fatal" in str(excinfo.value)

    # Verify we logged the specific safety error
    logger_mock = system.logger.create_module_logger.return_value
    error_calls = [str(call) for call in logger_mock.error.call_args_list]
    assert any("Safe fallback failed" in c for c in error_calls)
