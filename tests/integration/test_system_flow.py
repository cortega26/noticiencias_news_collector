import asyncio
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from news_collector.system import NewsCollectorSystem


@pytest.fixture
def mock_system_components():
    with (
        patch("news_collector.system.get_database_manager") as mock_db_fac,
        patch("news_collector.system.setup_logging") as mock_log,
        patch("news_collector.system.get_metrics_reporter"),
        patch(
            "news_collector.collectors.dispatcher.CollectorDispatcher"
        ) as mock_dispatcher_cls,
        patch("news_collector.system.ContentValidator") as mock_validator_cls,
        patch("news_collector.scoring.create_scorer"),
    ):

        # Setup mocks
        mock_db = MagicMock()
        mock_db_fac.return_value = mock_db
        mock_db.config = {"type": "sqlite"}

        mock_logger = MagicMock()
        mock_log.return_value = mock_logger

        mock_collector = MagicMock()
        mock_dispatcher_cls.return_value = mock_collector
        mock_collector.is_healthy.return_value = True

        mock_validator = MagicMock()
        mock_validator_cls.return_value = mock_validator

        yield {"db": mock_db, "collector": mock_collector, "validator": mock_validator}


def test_system_initialization(mock_system_components):
    # Setup health check success
    mock_system_components["db"].get_health_status.return_value = {
        "status": "healthy",
        "failed_sources": 0,
    }

    system = NewsCollectorSystem()
    system.initialize()
    assert system.is_initialized is True

    mock_system_components["db"].initialize_sources.assert_called()


@pytest.mark.asyncio
async def test_run_collection_cycle(mock_system_components):
    # Setup health check success
    mock_system_components["db"].get_health_status.return_value = {
        "status": "healthy",
        "failed_sources": 0,
    }

    system = NewsCollectorSystem()
    system.initialize()

    # Mock collection returns
    mock_system_components["collector"].collect_from_multiple_sources_async = AsyncMock(
        return_value={
            "source_details": {"test_source": {"success": True, "articles_saved": 5}}
        }
    )

    mock_system_components["validator"].validate_batch.return_value = {"invalid": []}

    with (
        patch.object(
            system, "_execute_scoring", new_callable=AsyncMock
        ) as mock_scoring,
        patch.object(system, "_execute_final_selection"),
        patch.object(system, "_generate_session_report") as mock_report,
        patch.object(system, "_record_collection_observability"),
    ):

        mock_scoring.return_value = {"statistics": {}}
        mock_report.return_value = {"summary": "success", "performance_metrics": {}}

        report = await system.run_collection_cycle(sources_filter=["test_source"])
        assert report["summary"] == "success"


def test_system_auxiliary_methods(mock_system_components):
    # Setup health
    mock_system_components["db"].get_health_status.return_value = {"status": "healthy"}
    system = NewsCollectorSystem()
    system.initialize()

    # Mock DB returns for top articles
    mock_article = MagicMock()
    mock_article.to_dict.return_value = {
        "id": 1,
        "title": "Top Art",
        "final_score": 0.9,
    }
    mock_system_components["db"].get_articles_by_score.return_value = [mock_article]

    # Mock reranker import or patch it
    with patch(
        "news_collector.reranker.rerank_articles",
        side_effect=lambda arts, **kwargs: arts,
    ):
        top = system.get_top_articles(limit=5)
        assert len(top) == 1
        assert top[0]["title"] == "Top Art"

    # Stats
    mock_system_components["db"].get_daily_stats.return_value = {"today": 10}
    stats = system.get_system_statistics()
    assert stats["system_info"]["is_healthy"] is True  # loosely true based on fixture

    # Export
    with (
        patch("builtins.open", new_callable=MagicMock) as mock_open_func,
        patch("json.dump"),
    ):

        # Mock open context manager
        mock_file = MagicMock()
        mock_open_func.return_value.__enter__.return_value = mock_file

        mock_system_components["db"].get_articles_by_score.return_value = [
            mock_article
        ]  # Reuse
        system.export_latest_articles("export.json")
        mock_open_func.assert_called_with(ANY, "w", encoding="utf-8")


@pytest.mark.asyncio
async def test_system_shutdown(mock_system_components):
    system = NewsCollectorSystem()
    system.initialize()
    system.collector.close = (
        AsyncMock()
        if asyncio.iscoroutinefunction(system.collector.close)
        else MagicMock()
    )

    await system.shutdown()
    mock_system_components["db"].close.assert_called()


def test_system_health_check_healthy(mock_system_components):
    system = NewsCollectorSystem()
    system.initialize()

    mock_system_components["db"].get_health_status.return_value = {
        "status": "healthy",
        "failed_sources": 0,
    }
    mock_system_components["collector"].is_healthy.return_value = True

    health = system._check_system_health()
    assert health["healthy"] is True


def test_system_health_check_unhealthy(mock_system_components):
    # Init must pass first
    mock_system_components["db"].get_health_status.return_value = {
        "status": "healthy",
        "failed_sources": 0,
    }

    system = NewsCollectorSystem()
    system.initialize()

    # Now simulate failure (Collector down is critical)
    mock_system_components["collector"].is_healthy.return_value = False

    health = system._check_system_health()
    assert health["healthy"] is False
    assert any("Colector" in issue for issue in health["issues"])
