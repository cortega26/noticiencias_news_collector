from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from news_collector.storage.models import Article
from news_collector.system import NewsCollectorSystem


@pytest.fixture
def mock_system_deps():
    with (
        patch(
            "news_collector.collectors.dispatcher.CollectorDispatcher"
        ) as mock_dispatcher,
        patch("news_collector.storage.database.get_database_manager") as mock_db,
        patch(
            "news_collector.enrichment.enrichment_pipeline.enrich_article"
        ) as mock_enrich,
        patch("news_collector.reranker.reranker.rerank_articles") as mock_rerank,
    ):

        # Setup Dispatcher
        dispatcher_instance = mock_dispatcher.return_value
        dispatcher_instance.collect_from_multiple_sources_async = AsyncMock()

        # Setup DB
        db_instance = mock_db.return_value

        yield {
            "dispatcher": dispatcher_instance,
            "db": db_instance,
            "enrich": mock_enrich,
            "rerank": mock_rerank,
        }


@pytest.fixture
def system(mock_system_deps):

    # We might need to mock internal scorer initialization
    sys = NewsCollectorSystem()
    # Inject mocks if they aren't automatically picked up by init
    # sys.dispatcher is set in __init__
    sys.collector = mock_system_deps["dispatcher"]
    sys.db_manager = mock_system_deps["db"]

    # Mock scorer
    sys.scorer = MagicMock()
    sys.scorer.score_article_async = AsyncMock()

    return sys

    import asyncio
    from datetime import datetime, timezone

    # Setup Data
    raw_article = Article(
        id="1",
        url="http://test.com",
        title="Test",
        source_id="s1",
        published_date=datetime.now(timezone.utc),
    )
    mock_system_deps["dispatcher"].collect_from_multiple_sources_async.return_value = {
        "source_details": {},
        "articles_saved": 1,
    }
    # Note: collect_from_multiple_sources_async returns a dict in system.py usage?
    # system.py line 687: returns await self.collector.collect_from_multiple_sources_async(...)
    # Let's trust the mock return.

    # Setup Enrichment
    mock_system_deps["enrich"].return_value = MagicMock(
        model_dump=MagicMock(return_value={"sentiment": "positive"})
    )

    # Setup Scorer
    system.scorer.score_article_async.return_value = {
        "final_score": 0.8,
        "should_include": True,
        "statistics": {},
    }

    # Setup Reranker
    mock_system_deps["rerank"].return_value = [{"article_id": "1", "score": 0.8}]

    # Mock DB to return pending articles for scoring
    mock_system_deps["db"].get_pending_articles.return_value = [raw_article]

    # Mock _execute_collection and _execute_scoring etc?
    # Or rely on mocking dependencies.
    # run_collection_cycle calls:
    # 1. _get_sources_to_process -> OK (no deps)
    # 2. _execute_collection -> calls self.collector.collect... -> Mocked!
    # 3. _execute_validation -> calls self.validator -> we didn't mock validator in fixture!
    #    We need to patch ContentValidator creation or the instance on system.
    #    system.py creates self.validator = ContentValidator() in _setup_validation.

    # We need to mock validator to avoid validation logic issues.
    # We need to mock validator to avoid validation logic issues.
    system.validator = MagicMock()
    # Ensure 'validated' list contains the article so it proceeds to scoring
    system.validator.validate_batch.return_value = {
        "validated_count": 1,
        "rejected_count": 0,
        "results": [{"id": "1", "status": "valid"}],
        "validated": [raw_article],
    }

    # 4. _execute_scoring -> calls self.scorer -> Mocked!
    # 5. _execute_final_selection -> internal logic
    # 6. _generate_session_report -> internal logic
    # 7. logger calls -> we should probably mock logger too to avoid noise but it's fine.

    # We need to mock internals that invoke complex dependencies if any.
    # But let's try calling it.

    # We must ensure system is initialized or mocked as initialized.
    system.is_initialized = True

    # Mock Logger
    system.logger = MagicMock()
    system.logger.create_module_logger.return_value = MagicMock()

    # Run
    # run_collection_cycle returns a dict report
    result = asyncio.run(system.run_collection_cycle(dry_run=False))

    # Verification
    assert "summary" in result
    assert "performance_metrics" in result

    # Verify calls
    mock_system_deps["dispatcher"].collect_from_multiple_sources_async.assert_called()
    system.scorer.score_article_async.assert_called()


def test_sync_wrapper(system):
    # Mock the async method on the system to test the wrapper
    # system.py does NOT have collect_and_process wrapper. It has run_collection_cycle (async).
    # So this test was hallucinatory. Removing it.
    pass
