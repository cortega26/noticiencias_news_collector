"""Tests for ScoringCoordinator — extracted from NewsCollectorSystem._execute_scoring."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from news_collector.scoring.coordinator import ScoringCoordinator


class _MockArticle:
    """Mimics SQLAlchemy Article model with fields the scoring adapter needs."""

    def __init__(self, **kwargs):
        self.id = kwargs.get("id", 1)
        self.title = kwargs.get("title", "Test Article")
        self.url = kwargs.get("url", "http://example.com/article")
        self.source_id = kwargs.get("source_id", "src1")
        self.source_name = kwargs.get("source_name", "Test Source")
        self.summary = kwargs.get("summary", "Test summary")
        self.content = kwargs.get("content", "Test content body")
        self.published_date = kwargs.get("published_date")
        self.collected_date = kwargs.get("collected_date")
        self.final_score = kwargs.get("final_score", 0.5)
        self.article_metadata = kwargs.get("article_metadata", {})
        self.authors = kwargs.get("authors", [])
        self.category = kwargs.get("category", "gen")
        self.peer_reviewed = kwargs.get("peer_reviewed", False)
        self.is_preprint = kwargs.get("is_preprint", False)
        self.doi = kwargs.get("doi")
        self.journal = kwargs.get("journal")
        self.duplication_confidence = kwargs.get("duplication_confidence", 0.1)
        self.word_count = kwargs.get("word_count", 100)

    def to_dict(self):
        return self.__dict__.copy()


@pytest.fixture
def coordinator():
    db = MagicMock()
    scorer = MagicMock()
    logger = MagicMock()
    logger.create_module_logger.return_value = logger
    return ScoringCoordinator(
        db_manager=db, scorer=scorer, logger=logger, config_override={}
    )


class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_returns_simulated_results(self, coordinator):
        result = await coordinator.execute(
            {"collection_summary": {"articles_found": 5}}, dry_run=True
        )
        assert result["success"] is True
        assert result["statistics"]["articles_scored"] == 5
        coordinator.db_manager.get_pending_articles.assert_not_called()
        coordinator.scorer.score_batch_async.assert_not_called()


class TestBatchPath:
    @pytest.mark.asyncio
    async def test_batch_scoring_success(self, coordinator):
        articles = [_MockArticle(id=1, title="A"), _MockArticle(id=2, title="B")]
        coordinator.db_manager.get_pending_articles.return_value = articles
        coordinator.scorer.score_batch_async = AsyncMock(
            return_value=[
                {"final_score": 0.8, "should_include": True},
                {"final_score": 0.3, "should_include": False},
            ]
        )
        coordinator.db_manager.update_articles_score_bulk.return_value = True

        result = await coordinator.execute({}, dry_run=False)

        assert result["success"] is True
        assert result["statistics"]["articles_scored"] == 2
        assert result["statistics"]["articles_included"] == 1
        assert result["statistics"]["articles_excluded"] == 1
        assert result["statistics"]["average_score"] == 0.55
        assert result["processed_articles"] == 2
        coordinator.db_manager.update_articles_score_bulk.assert_called_once()

    @pytest.mark.asyncio
    async def test_batch_failure_falls_back_to_sequential(self, coordinator):
        articles = [_MockArticle(id=1, title="A")]
        coordinator.db_manager.get_pending_articles.return_value = articles
        # Batch fails
        coordinator.scorer.score_batch_async = AsyncMock(
            side_effect=RuntimeError("Batch OOM")
        )
        # Sequential fallback succeeds
        coordinator.scorer.score_article_async = AsyncMock(
            return_value={"final_score": 0.7, "should_include": True}
        )
        coordinator.db_manager.update_articles_score_bulk.return_value = True

        result = await coordinator.execute({}, dry_run=False)

        assert result["success"] is True
        assert result["statistics"]["articles_scored"] == 1
        assert result["statistics"]["articles_included"] == 1
        coordinator.logger.error.assert_called_once()  # batch failure logged
        coordinator.scorer.score_article_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_batch_failure_raises_when_no_fallback(self, coordinator):
        articles = [_MockArticle(id=1, title="A")]
        coordinator.db_manager.get_pending_articles.return_value = articles
        coordinator.scorer.score_batch_async = AsyncMock(
            side_effect=RuntimeError("Batch OOM")
        )
        # No score_article_async available
        if hasattr(coordinator.scorer, "score_article_async"):
            del coordinator.scorer.score_article_async

        with pytest.raises(RuntimeError, match="Batch OOM"):
            await coordinator.execute({}, dry_run=False)


class TestSequentialPath:
    @pytest.mark.asyncio
    async def test_sequential_when_no_batch_method(self, coordinator):
        articles = [_MockArticle(id=1, title="A")]
        coordinator.db_manager.get_pending_articles.return_value = articles
        # No batch method — should go straight to sequential
        if hasattr(coordinator.scorer, "score_batch_async"):
            del coordinator.scorer.score_batch_async
        coordinator.scorer.score_article_async = AsyncMock(
            return_value={"final_score": 0.6, "should_include": True}
        )
        coordinator.db_manager.update_articles_score_bulk.return_value = True

        result = await coordinator.execute({}, dry_run=False)

        assert result["success"] is True
        assert result["processed_articles"] == 1
        coordinator.scorer.score_article_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_sequential_handles_exception_per_article(self, coordinator):
        articles = [_MockArticle(id=1, title="A"), _MockArticle(id=2, title="B")]
        coordinator.db_manager.get_pending_articles.return_value = articles
        if hasattr(coordinator.scorer, "score_batch_async"):
            del coordinator.scorer.score_batch_async
        # One succeeds, one throws
        coordinator.scorer.score_article_async = AsyncMock(
            side_effect=[
                {"final_score": 0.9, "should_include": True},
                RuntimeError("Article scoring failed"),
            ]
        )
        coordinator.db_manager.update_articles_score_bulk.return_value = True

        result = await coordinator.execute({}, dry_run=False)

        assert result["statistics"]["articles_scored"] == 1  # only one counted
        assert result["statistics"]["articles_included"] == 1
        coordinator.logger.error.assert_called()


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_payloads(self, coordinator):
        coordinator.db_manager.get_pending_articles.return_value = []

        result = await coordinator.execute({}, dry_run=False)

        assert result["success"] is True
        assert result["processed_articles"] == 0
        coordinator.scorer.score_batch_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_excluded(self, coordinator):
        articles = [_MockArticle(id=1, title="A")]
        coordinator.db_manager.get_pending_articles.return_value = articles
        coordinator.scorer.score_batch_async = AsyncMock(
            return_value=[{"final_score": 0.1, "should_include": False}]
        )
        coordinator.db_manager.update_articles_score_bulk.return_value = True

        result = await coordinator.execute({}, dry_run=False)

        assert result["statistics"]["articles_excluded"] == 1
        assert result["statistics"]["articles_included"] == 0

    @pytest.mark.asyncio
    async def test_bulk_update_failure_logged(self, coordinator):
        articles = [_MockArticle(id=1, title="A")]
        coordinator.db_manager.get_pending_articles.return_value = articles
        coordinator.scorer.score_batch_async = AsyncMock(
            return_value=[{"final_score": 0.8, "should_include": True}]
        )
        coordinator.db_manager.update_articles_score_bulk.return_value = False

        await coordinator.execute({}, dry_run=False)

        # Error logged but doesn't crash
        coordinator.logger.error.assert_called_with(
            "Failed to perform bulk score updates."
        )


class TestRescoring:
    @pytest.mark.asyncio
    async def test_rescoring_fetches_and_scores_both_pending_and_completed(self, coordinator):
        pending = [_MockArticle(id=1, title="Pending A", source_id="src1")]
        completed = [_MockArticle(id=2, title="Completed B", source_id="src1")]

        coordinator.db_manager.get_pending_articles.return_value = pending
        coordinator.db_manager.get_completed_articles_for_rescoring.return_value = completed

        coordinator.scorer.score_batch_async = AsyncMock(
            return_value=[
                {"final_score": 0.8, "should_include": True},
                {"final_score": 0.65, "should_include": True},
            ]
        )
        coordinator.db_manager.update_articles_score_bulk.return_value = True

        result = await coordinator.execute({}, dry_run=False)

        assert result["success"] is True
        # Verify stats detail both
        assert result["statistics"]["articles_scored"] == 2
        assert result["statistics"]["new_articles_scored"] == 1
        assert result["statistics"]["completed_articles_rescored"] == 1
        assert result["statistics"]["articles_included"] == 2
        assert result["statistics"]["average_score"] == 0.725
        assert result["processed_articles"] == 2

        # Verify rescore lookback read from config defaults to 14
        coordinator.db_manager.get_completed_articles_for_rescoring.assert_called_once_with(days_back=14)

        # Verify both payloads are passed to scorer
        coordinator.scorer.score_batch_async.assert_called_once()
        called_payloads = coordinator.scorer.score_batch_async.call_args[0][0]
        assert len(called_payloads) == 2
        assert called_payloads[0]["title"] == "Pending A"
        assert called_payloads[1]["title"] == "Completed B"

        # Verify bulk updates received both
        coordinator.db_manager.update_articles_score_bulk.assert_called_once()
        called_updates = coordinator.db_manager.update_articles_score_bulk.call_args[0][0]
        assert len(called_updates) == 2
        assert called_updates[0] == (1, {"final_score": 0.8, "should_include": True})
        assert called_updates[1] == (2, {"final_score": 0.65, "should_include": True})

    @pytest.mark.asyncio
    async def test_rescoring_lookback_override(self, coordinator):
        coordinator.config_override = {"rescore_days_back": 7}
        coordinator.db_manager.get_pending_articles.return_value = []
        coordinator.db_manager.get_completed_articles_for_rescoring.return_value = []

        await coordinator.execute({}, dry_run=False)

        # Verify lookback overridden correctly
        coordinator.db_manager.get_completed_articles_for_rescoring.assert_called_once_with(days_back=7)

