"""Tests for ScoringCoordinator — extracted from NewsCollectorSystem._execute_scoring.

Plan 036 rewrite: the coordinator now pages through
`get_pending_articles_page`/`get_completed_articles_for_rescoring_page`
instead of loading the whole backlog via the unpaged methods, so every
fixture here builds `ArticlePage`/`ArticleCursor` objects (page-at-a-time
semantics) rather than plain lists returned in one call. This is an
intentional behavior change per plan 036's own Test Plan, not a
regression — the old single-call assertions no longer hold under paging.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_collector.scoring.coordinator import ScoringCoordinator
from news_collector.storage.article_repository import ArticleCursor, ArticlePage


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
        self.collected_date = kwargs.get(
            "collected_date", datetime(2026, 1, 1, tzinfo=timezone.utc)
        )
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


def _cursor(article):
    return ArticleCursor(collected_date=article.collected_date, id=article.id)


def _page(items, next_cursor=None):
    return ArticlePage(items=items, next_cursor=next_cursor)


_EMPTY_PAGE = ArticlePage(items=[], next_cursor=None)


@pytest.fixture
def coordinator():
    db = MagicMock()
    scorer = MagicMock()
    logger = MagicMock()
    logger.create_module_logger.return_value = logger
    return ScoringCoordinator(
        db_manager=db, scorer=scorer, logger=logger, config_override={}
    )


def _batch_scores(final_score=0.7, should_include=True):
    """AsyncMock side_effect: one uniform score per payload, any page size."""

    def _score(payloads):
        return [
            {"final_score": final_score, "should_include": should_include}
            for _ in payloads
        ]

    return AsyncMock(side_effect=_score)


class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_returns_simulated_results(self, coordinator):
        result = await coordinator.execute(
            {"collection_summary": {"articles_found": 5}}, dry_run=True
        )
        assert result["success"] is True
        assert result["statistics"]["articles_scored"] == 5
        coordinator.db_manager.get_pending_articles_page.assert_not_called()
        coordinator.scorer.score_batch_async.assert_not_called()


class TestBatchPath:
    @pytest.mark.asyncio
    async def test_batch_scoring_success(self, coordinator):
        articles = [_MockArticle(id=1, title="A"), _MockArticle(id=2, title="B")]
        coordinator.db_manager.get_pending_articles_page.return_value = _page(
            articles
        )
        coordinator.db_manager.get_completed_articles_for_rescoring_page.return_value = (
            _EMPTY_PAGE
        )
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
        assert result["stop_reason"] == "exhausted"
        coordinator.db_manager.update_articles_score_bulk.assert_called_once()

    @pytest.mark.asyncio
    async def test_batch_failure_falls_back_to_sequential(self, coordinator):
        articles = [_MockArticle(id=1, title="A")]
        coordinator.db_manager.get_pending_articles_page.return_value = _page(
            articles
        )
        coordinator.db_manager.get_completed_articles_for_rescoring_page.return_value = (
            _EMPTY_PAGE
        )
        coordinator.scorer.score_batch_async = AsyncMock(
            side_effect=RuntimeError("Batch OOM")
        )
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
        coordinator.db_manager.get_pending_articles_page.return_value = _page(
            articles
        )
        coordinator.db_manager.get_completed_articles_for_rescoring_page.return_value = (
            _EMPTY_PAGE
        )
        coordinator.scorer.score_batch_async = AsyncMock(
            side_effect=RuntimeError("Batch OOM")
        )
        if hasattr(coordinator.scorer, "score_article_async"):
            del coordinator.scorer.score_article_async

        with pytest.raises(RuntimeError, match="Batch OOM"):
            await coordinator.execute({}, dry_run=False)


class TestSequentialPath:
    @pytest.mark.asyncio
    async def test_sequential_when_no_batch_method(self, coordinator):
        articles = [_MockArticle(id=1, title="A")]
        coordinator.db_manager.get_pending_articles_page.return_value = _page(
            articles
        )
        coordinator.db_manager.get_completed_articles_for_rescoring_page.return_value = (
            _EMPTY_PAGE
        )
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
        coordinator.db_manager.get_pending_articles_page.return_value = _page(
            articles
        )
        coordinator.db_manager.get_completed_articles_for_rescoring_page.return_value = (
            _EMPTY_PAGE
        )
        if hasattr(coordinator.scorer, "score_batch_async"):
            del coordinator.scorer.score_batch_async
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

    @pytest.mark.asyncio
    async def test_fallback_concurrency_is_bounded(self, coordinator):
        """Step 4: the sequential fallback must never exceed the
        configured worker limit's in-flight concurrency."""
        articles = [_MockArticle(id=i, title=f"A{i}") for i in range(1, 9)]
        coordinator.db_manager.get_pending_articles_page.return_value = _page(
            articles
        )
        coordinator.db_manager.get_completed_articles_for_rescoring_page.return_value = (
            _EMPTY_PAGE
        )
        if hasattr(coordinator.scorer, "score_batch_async"):
            del coordinator.scorer.score_batch_async
        coordinator.config_override = {"scoring_workers": 2}

        in_flight = 0
        max_in_flight = 0
        lock = asyncio.Lock()

        async def _score_article(payload):
            nonlocal in_flight, max_in_flight
            async with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.01)
            async with lock:
                in_flight -= 1
            return {"final_score": 0.5, "should_include": True}

        coordinator.scorer.score_article_async = AsyncMock(
            side_effect=_score_article
        )
        coordinator.db_manager.update_articles_score_bulk.return_value = True

        result = await coordinator.execute({}, dry_run=False)

        assert result["statistics"]["articles_scored"] == 8
        assert max_in_flight <= 2
        # The coordinator's own telemetry must observe the same bound.
        assert result["telemetry"]["max_fallback_inflight_observed"] <= 2
        assert result["telemetry"]["max_fallback_inflight_observed"] >= 1


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_payloads(self, coordinator):
        coordinator.db_manager.get_pending_articles_page.return_value = _EMPTY_PAGE
        coordinator.db_manager.get_completed_articles_for_rescoring_page.return_value = (
            _EMPTY_PAGE
        )

        result = await coordinator.execute({}, dry_run=False)

        assert result["success"] is True
        assert result["processed_articles"] == 0
        coordinator.scorer.score_batch_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_excluded(self, coordinator):
        articles = [_MockArticle(id=1, title="A")]
        coordinator.db_manager.get_pending_articles_page.return_value = _page(
            articles
        )
        coordinator.db_manager.get_completed_articles_for_rescoring_page.return_value = (
            _EMPTY_PAGE
        )
        coordinator.scorer.score_batch_async = AsyncMock(
            return_value=[{"final_score": 0.1, "should_include": False}]
        )
        coordinator.db_manager.update_articles_score_bulk.return_value = True

        result = await coordinator.execute({}, dry_run=False)

        assert result["statistics"]["articles_excluded"] == 1
        assert result["statistics"]["articles_included"] == 0

    @pytest.mark.asyncio
    async def test_bulk_update_failure_stops_cycle_as_failure(self, coordinator):
        articles = [_MockArticle(id=1, title="A")]
        coordinator.db_manager.get_pending_articles_page.return_value = _page(
            articles
        )
        coordinator.db_manager.get_completed_articles_for_rescoring_page.return_value = (
            _EMPTY_PAGE
        )
        coordinator.scorer.score_batch_async = AsyncMock(
            return_value=[{"final_score": 0.8, "should_include": True}]
        )
        coordinator.db_manager.update_articles_score_bulk.return_value = False

        result = await coordinator.execute({}, dry_run=False)

        # Persistence failure is surfaced as a cycle failure, not swallowed.
        assert result["success"] is False
        assert result["stop_reason"] == "persistence_failed"
        assert result["statistics"]["articles_scored"] == 0
        coordinator.logger.error.assert_called_with(
            "Failed to perform bulk score updates."
        )


class TestPaging:
    @pytest.mark.asyncio
    async def test_multiple_pages_are_aggregated(self, coordinator):
        page1_articles = [_MockArticle(id=1, title="A")]
        page2_articles = [_MockArticle(id=2, title="B")]
        cursor1 = _cursor(page1_articles[0])

        coordinator.db_manager.get_pending_articles_page.side_effect = [
            _page(page1_articles, next_cursor=cursor1),
            _page(page2_articles, next_cursor=None),
        ]
        coordinator.db_manager.get_completed_articles_for_rescoring_page.return_value = (
            _EMPTY_PAGE
        )
        coordinator.scorer.score_batch_async = _batch_scores()
        coordinator.db_manager.update_articles_score_bulk.return_value = True

        result = await coordinator.execute({}, dry_run=False)

        assert result["success"] is True
        assert result["statistics"]["articles_scored"] == 2
        assert result["pages_processed"] == 2
        assert coordinator.db_manager.get_pending_articles_page.call_count == 2
        assert coordinator.db_manager.update_articles_score_bulk.call_count == 2

    @pytest.mark.asyncio
    async def test_persistence_failure_on_second_page_keeps_first_page_committed(
        self, coordinator
    ):
        page1_articles = [_MockArticle(id=1, title="A")]
        page2_articles = [_MockArticle(id=2, title="B")]
        cursor1 = _cursor(page1_articles[0])

        coordinator.db_manager.get_pending_articles_page.side_effect = [
            _page(page1_articles, next_cursor=cursor1),
            _page(page2_articles, next_cursor=None),
        ]
        coordinator.db_manager.get_completed_articles_for_rescoring_page.return_value = (
            _EMPTY_PAGE
        )
        coordinator.scorer.score_batch_async = _batch_scores()
        coordinator.db_manager.update_articles_score_bulk.side_effect = [True, False]

        result = await coordinator.execute({}, dry_run=False)

        assert result["success"] is False
        assert result["stop_reason"] == "persistence_failed"
        # Only page 1 counted — page 2's scores were never persisted.
        assert result["statistics"]["articles_scored"] == 1
        assert result["failed_cursor"] == {
            "collected_date": cursor1.collected_date,
            "id": cursor1.id,
        }
        # The rescore source is never reached once the cycle stops.
        coordinator.db_manager.get_completed_articles_for_rescoring_page.assert_not_called()

    @pytest.mark.asyncio
    async def test_cross_source_duplicate_id_scored_at_most_once(self, coordinator):
        shared = _MockArticle(id=5, title="Shared")
        pending_only = _MockArticle(id=6, title="PendingOnly")

        coordinator.db_manager.get_pending_articles_page.return_value = _page(
            [shared, pending_only]
        )
        coordinator.db_manager.get_completed_articles_for_rescoring_page.return_value = _page(
            [_MockArticle(id=5, title="Shared-dup")]
        )
        coordinator.scorer.score_batch_async = _batch_scores()
        coordinator.db_manager.update_articles_score_bulk.return_value = True

        result = await coordinator.execute({}, dry_run=False)

        assert result["statistics"]["articles_scored"] == 2  # id 5 counted once

    @pytest.mark.asyncio
    async def test_cycle_item_budget_stops_before_next_page(
        self, coordinator, monkeypatch
    ):
        page1_articles = [_MockArticle(id=1, title="A")]
        page2_articles = [_MockArticle(id=2, title="B")]
        cursor1 = _cursor(page1_articles[0])

        coordinator.db_manager.get_pending_articles_page.side_effect = [
            _page(page1_articles, next_cursor=cursor1),
            _page(page2_articles, next_cursor=None),
        ]
        coordinator.db_manager.get_completed_articles_for_rescoring_page.return_value = (
            _EMPTY_PAGE
        )
        coordinator.scorer.score_batch_async = _batch_scores()
        coordinator.db_manager.update_articles_score_bulk.return_value = True

        class _FakeSnapshot:
            scoring_config = {
                "page_size": 200,
                "workers": 4,
                "rescore_days_back": 14,
                "cycle_item_budget": 1,
            }

        monkeypatch.setattr(
            "news_collector.scoring.coordinator.get_runtime_config",
            lambda: _FakeSnapshot(),
        )

        result = await coordinator.execute({}, dry_run=False)

        assert result["stop_reason"] == "budget_reached"
        assert result["statistics"]["articles_scored"] == 1
        # The second page is never fetched once the budget is reached.
        assert coordinator.db_manager.get_pending_articles_page.call_count == 1
        coordinator.db_manager.get_completed_articles_for_rescoring_page.assert_not_called()


class TestTelemetry:
    @pytest.mark.asyncio
    async def test_telemetry_reports_pages_committed_and_stop_reason(
        self, coordinator
    ):
        articles = [_MockArticle(id=1, title="A"), _MockArticle(id=2, title="B")]
        coordinator.db_manager.get_pending_articles_page.return_value = _page(
            articles
        )
        coordinator.db_manager.get_completed_articles_for_rescoring_page.return_value = (
            _EMPTY_PAGE
        )
        coordinator.scorer.score_batch_async = _batch_scores()
        coordinator.db_manager.update_articles_score_bulk.return_value = True

        result = await coordinator.execute({}, dry_run=False)

        telemetry = result["telemetry"]
        assert telemetry["pages_processed"] == 1
        assert telemetry["committed"] == 2
        assert telemetry["failed"] == 0
        assert telemetry["stop_reason"] == "exhausted"
        assert telemetry["duration_sec"] >= 0.0

    @pytest.mark.asyncio
    async def test_telemetry_counts_per_article_scoring_failures(self, coordinator):
        articles = [_MockArticle(id=1, title="A"), _MockArticle(id=2, title="B")]
        coordinator.db_manager.get_pending_articles_page.return_value = _page(
            articles
        )
        coordinator.db_manager.get_completed_articles_for_rescoring_page.return_value = (
            _EMPTY_PAGE
        )
        coordinator.scorer.score_batch_async = AsyncMock(
            return_value=[
                {"final_score": 0.8, "should_include": True},
                RuntimeError("boom"),
            ]
        )
        coordinator.db_manager.update_articles_score_bulk.return_value = True

        result = await coordinator.execute({}, dry_run=False)

        assert result["telemetry"]["committed"] == 1
        assert result["telemetry"]["failed"] == 1

    @pytest.mark.asyncio
    async def test_telemetry_merges_scorer_cycle_telemetry_when_available(
        self, coordinator
    ):
        articles = [_MockArticle(id=1, title="A")]
        coordinator.db_manager.get_pending_articles_page.return_value = _page(
            articles
        )
        coordinator.db_manager.get_completed_articles_for_rescoring_page.return_value = (
            _EMPTY_PAGE
        )
        coordinator.scorer.score_batch_async = _batch_scores()
        coordinator.scorer.get_cycle_telemetry = MagicMock(
            return_value={"llm_calls": 3, "cache_hits": 7}
        )
        coordinator.db_manager.update_articles_score_bulk.return_value = True

        result = await coordinator.execute({}, dry_run=False)

        assert result["telemetry"]["llm_calls"] == 3
        assert result["telemetry"]["cache_hits"] == 7


class TestRescoring:
    @pytest.mark.asyncio
    async def test_rescoring_fetches_and_scores_both_pending_and_completed(
        self, coordinator
    ):
        pending = [_MockArticle(id=1, title="Pending A", source_id="src1")]
        completed = [_MockArticle(id=2, title="Completed B", source_id="src1")]

        coordinator.db_manager.get_pending_articles_page.return_value = _page(
            pending
        )
        coordinator.db_manager.get_completed_articles_for_rescoring_page.return_value = _page(
            completed
        )
        coordinator.scorer.score_batch_async = AsyncMock(
            side_effect=[
                [{"final_score": 0.8, "should_include": True}],
                [{"final_score": 0.65, "should_include": True}],
            ]
        )
        coordinator.db_manager.update_articles_score_bulk.return_value = True

        result = await coordinator.execute({}, dry_run=False)

        assert result["success"] is True
        assert result["statistics"]["articles_scored"] == 2
        assert result["statistics"]["new_articles_scored"] == 1
        assert result["statistics"]["completed_articles_rescored"] == 1
        assert result["statistics"]["articles_included"] == 2
        assert result["statistics"]["average_score"] == pytest.approx(0.725)
        assert result["processed_articles"] == 2

        # Verify rescore lookback read from config defaults to 14
        _, kwargs = coordinator.db_manager.get_completed_articles_for_rescoring_page.call_args
        assert kwargs["days_back"] == 14

        # Verify both bulk-update calls (one per page/source) happened.
        assert coordinator.db_manager.update_articles_score_bulk.call_count == 2

    @pytest.mark.asyncio
    async def test_rescoring_lookback_override(self, coordinator):
        coordinator.config_override = {"rescore_days_back": 7}
        coordinator.db_manager.get_pending_articles_page.return_value = _EMPTY_PAGE
        coordinator.db_manager.get_completed_articles_for_rescoring_page.return_value = (
            _EMPTY_PAGE
        )

        await coordinator.execute({}, dry_run=False)

        _, kwargs = coordinator.db_manager.get_completed_articles_for_rescoring_page.call_args
        assert kwargs["days_back"] == 7
