from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from news_collector.system import NewsCollectorSystem, bootstrap


class TestS1RefactorSafety:
    """
    Focused regression tests to verify S1 refactor safety contracts.
    """

    @pytest.fixture
    def mock_logger(self):
        with patch("news_collector.system.bootstrap.setup_logging") as mock:
            logger = MagicMock()
            mock.return_value = logger
            yield logger

    @pytest.fixture
    def mock_db(self):
        with patch("news_collector.system.bootstrap.get_database_manager") as mock:
            db = MagicMock()
            db.config = {"type": "test_sqlite"}
            db.get_health_status.return_value = {
                "status": "healthy",
                "failed_sources": 0,
            }
            mock.return_value = db
            yield db

    @pytest.fixture
    def mock_collectors(self):
        with patch("news_collector.collectors.dispatcher.CollectorDispatcher") as mock:
            dispatcher = MagicMock()
            dispatcher.is_healthy.return_value = True
            # Async pipeline calls wait directly on result, so simple return is enough if awaited?
            # No, if pipeline awaits it, it must be awaitable.
            # But the dispatcher methods in the real code are defined as async or not.
            # Let's set default side_effects to be safe if called.
            mock.return_value = dispatcher
            yield dispatcher

    @pytest.fixture
    def mock_scorer(self):
        with patch("news_collector.scoring.create_scorer") as mock:
            scorer = MagicMock()
            mock.return_value = scorer
            yield scorer

    @pytest.fixture
    def system(self, mock_logger, mock_db, mock_collectors, mock_scorer):
        """Creates a fresh system instance for each test."""
        # Mock validations to pass
        with (
            patch("news_collector.system.bootstrap.validate_config"),
            patch("news_collector.system.bootstrap.validate_sources"),
        ):
            sys = NewsCollectorSystem()
            return sys

    def test_initialization_contract(self, system):
        """
        Contract: initialize() must return True and set is_initialized=True
        and populated core dependencies (db, collector, etc).
        """
        assert system.is_initialized is False

        success = system.initialize()

        assert success is True
        assert system.is_initialized is True
        assert system.db_manager is not None
        assert system.collector is not None
        assert system.scorer is not None
        assert system.logger is not None

        # Verify bootstrap calls happened (indirectly via existence of components)
        assert system.db_manager.get_health_status.called

    @pytest.mark.asyncio
    async def test_collection_cycle_contract_dry_run(self, system):
        """
        Contract: run_collection_cycle(dry_run=True) returns a report
        with specific keys (summary, performance etc).
        """
        system.initialize()

        # Mock execution phases
        # For methods called with await in pipeline.py, use AsyncMock
        system._execute_collection = AsyncMock(
            return_value={
                "source_details": {},
                "collection_summary": {
                    "sources_processed": 5,
                    "articles_found": 10,
                    "articles_saved": 0,
                },
            }
        )
        system._execute_validation = MagicMock(
            return_value={"validated_count": 0, "rejected_count": 0}
        )
        system._execute_scoring = AsyncMock(return_value={"statistics": {}})
        system._execute_final_selection = MagicMock(return_value={"selected_count": 0})
        system._generate_session_report = MagicMock(
            return_value={
                "summary": {"test": "ok"},
                "performance_metrics": {},
                "details": {},
            }
        )

        report = await system.run_collection_cycle(dry_run=True)

        assert "summary" in report
        assert "performance_metrics" in report
        assert "details" in report
        assert report["summary"] == {"test": "ok"}

    @pytest.mark.asyncio
    async def test_collector_dispatch_paths(self, system):
        """
        Contract: Pipeline delegates to collector.collect_from_multiple_sources_async
        if available, falling back to sync.
        """
        system.initialize()

        # Case A: Async Collector
        # The dispatcher mock needs to have the async method
        system.collector.collect_from_multiple_sources_async = AsyncMock(
            return_value={}
        )

        await system.run_collection_cycle(dry_run=True)
        # Should verify it called async method
        assert system.collector.collect_from_multiple_sources_async.called

        # Case B: Sync Collector Only
        # We need to ensure the async method is NOT present or raises AttributeError
        del system.collector.collect_from_multiple_sources_async

        # NOTE: pipeline.py checks hasattr(self.collector, "collect_from_multiple_sources_async")
        # In a generic mock, getting an attribute usually creates a child mock.
        # We must explicitly ensure it behaves as missing.
        # However, del on a mock doesn't always work as expected for getattr.
        # Better: create a new mock that definitely doesn't have it

        sync_collector = MagicMock()
        # Mock specs are safer but let's just use del and spec=list or something,
        # or just configure the mock property to raise AttributeError?
        # Actually pipeline.py does: if hasattr(...)
        # For a MagicMock, hasattr usually returns True.

        # Let's force the system.collector re-assignment
        system.collector = MagicMock(spec=[])  # Empty spec
        system.collector.collect_from_multiple_sources = MagicMock(return_value={})
        # hasattr(system.collector, "collect_from_multiple_sources_async") should be false if not in spec?
        # Or easier:

        # Let's rely on standard logic: if we don't define it and spec it properly.
        # BUT simplest way:
        class SyncCollector:
            def collect_from_multiple_sources(self, *args, **kwargs):
                return {}

        system.collector = SyncCollector()
        system.collector.collect_from_multiple_sources = MagicMock(return_value={})

        await system.run_collection_cycle(dry_run=True)
        # Should verify it called sync method
        assert system.collector.collect_from_multiple_sources.called

    @pytest.mark.asyncio
    async def test_legacy_api_delegation(self, system):
        """
        Verify legacy public methods still work (smoke test).
        """
        system.initialize()

        # Test shutdown
        system.collector.close = MagicMock()
        await system.shutdown()
        assert system.collector.close.called
        assert system.db_manager.close.called

        # Test get_top_articles
        system.db_manager.get_articles_by_score.return_value = []
        # Mock reranker import or logic if needed, but if DB returns empty, it might skip reranker or handle empty
        # Real code imports inside the method: from news_collector.reranker import rerank_articles
        # We need to mock that import or the function
        with patch(
            "news_collector.reranker.rerank_articles", return_value=[]
        ) as mock_rank:
            res = system.get_top_articles(limit=5)
            assert res == []

        # Test export
        system.db_manager.get_articles_by_score.return_value = []
        export = system.export_latest_articles()
        assert export["article_count"] == 0

    def test_bootstrap_error_handling(self, system):
        """
        Verify bootstrap failure logic.
        """
        with patch(
            "news_collector.system.bootstrap.build_database",
            side_effect=Exception("DB Boom"),
        ):
            success = system.initialize()
            assert success is False
            assert system.is_initialized is False

    def test_system_stats(self, system):
        """
        Verify stats delegation.
        """
        system.initialize()
        system.db_manager.get_health_status.return_value = {"status": "ok"}
        system.db_manager.get_daily_stats.return_value = {}
        system.db_manager.get_top_sources_performance.return_value = []

        stats = system.get_system_statistics()
        assert "system_info" in stats

    def test_health_check_branches(self):
        """
        Verify specific health check branches in bootstrap for high coverage.
        """
        logger = MagicMock()
        db = MagicMock()
        collector = MagicMock()

        # 1. DB Warning (failed sources > 0)
        db.get_health_status.return_value = {"failed_sources": 5}
        collector.is_healthy.return_value = True

        res = bootstrap.check_system_health(db, collector, logger, {"s1": {}})
        assert "5 fuentes fallando" in res["warnings"][0]

        # 2. DB Exception
        db.get_health_status.side_effect = Exception("DB Down")
        res = bootstrap.check_system_health(db, collector, logger, {"s1": {}})
        assert res["healthy"] is False
        assert "Error verificando base de datos" in res["issues"][0]

        # 3. Collector Unhealthy
        db.get_health_status.side_effect = None
        db.get_health_status.return_value = {"failed_sources": 0}
        collector.is_healthy.return_value = False

        res = bootstrap.check_system_health(db, collector, logger, {"s1": {}})
        assert res["healthy"] is False
        assert "Colector en estado no saludable" in res["issues"][0]

        # 4. No sources config
        collector.is_healthy.return_value = True
        res = bootstrap.check_system_health(db, collector, logger, {})
        assert res["healthy"] is False
        assert "No hay fuentes configuradas" in res["issues"][0]

    def test_build_collectors_error(self):
        """
        Verify fatal error in collector construction.
        """
        logger = MagicMock()
        # Mocking import inside function or the constructor call
        # Since the function does 'from ... import ...', we can patch the class constructor
        with patch(
            "news_collector.collectors.dispatcher.CollectorDispatcher",
            side_effect=Exception("Dispatcher Fail"),
        ):
            with pytest.raises(Exception) as exc:
                bootstrap.build_collectors(logger, None)
            assert "Dispatcher Fail" in str(exc.value)

    def test_observability_coverage(self):
        """
        Verify observability module logic specifically for coverage.
        """
        from news_collector.system import observability

        logger = MagicMock()
        metrics = MagicMock()

        # Test record_collection_outcomes with mixed results
        results = {
            "source_details": {
                "s1": {"success": True, "articles_saved": 5, "processing_time": 0.1},
                "s2": {
                    "success": False,
                    "error_message": "Timeout",
                    "processing_time": 0.2,
                },
            }
        }

        observability.record_collection_outcomes(
            logger, metrics, results, "sess-1", "trace-1"
        )

        # Verify logger calls - create_module_logger call
        assert logger.create_module_logger.called
        collector_logger = logger.create_module_logger.return_value

        # Verify success path
        assert collector_logger.info.called
        assert metrics.record_ingest.called

        # Verify failure path
        assert collector_logger.warning.called
        assert metrics.record_error.called
