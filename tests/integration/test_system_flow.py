import asyncio
from datetime import datetime, timezone
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from news_collector.system import NewsCollectorSystem


@pytest.fixture
def mock_system_components():
    with (
        patch("news_collector.system.bootstrap.build_database") as mock_build_db,
        patch("news_collector.system.bootstrap.build_logging") as mock_build_log,
        patch("news_collector.system.bootstrap.build_metrics"),
        patch("news_collector.system.bootstrap.build_collectors") as mock_build_coll,
        patch("news_collector.system.bootstrap.build_validator") as mock_build_val,
        patch("news_collector.system.bootstrap.build_scorer"),
        patch("news_collector.system.bootstrap.check_system_health") as mock_health,
        patch("news_collector.system.bootstrap.validate_system_config"),
    ):

        # Setup mocks
        mock_db = MagicMock()
        mock_build_db.return_value = mock_db
        mock_db.config = {"type": "sqlite"}
        # Default health check for initialize
        mock_health.return_value = {"healthy": True, "issues": [], "warnings": []}

        mock_logger = MagicMock()
        mock_sys_logger = MagicMock()
        mock_build_log.return_value = (mock_logger, mock_sys_logger)

        mock_collector = MagicMock()
        mock_build_coll.return_value = mock_collector
        # Default healthy
        mock_collector.is_healthy.return_value = True

        mock_validator = MagicMock()
        mock_build_val.return_value = mock_validator

        yield {"db": mock_db, "collector": mock_collector, "validator": mock_validator, "logger": mock_logger}


def test_system_initialization(mock_system_components):
    # Setup health check success
    mock_system_components["db"].get_health_status.return_value = {
        "status": "healthy",
        "failed_sources": 0,
    }

    system = NewsCollectorSystem()
    system.initialize()
    assert system.is_initialized is True


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

    ):

        mock_scoring.return_value = {"statistics": {}}
        mock_report.return_value = {"summary": "success", "performance_metrics": {}}

        report = await system.run_collection_cycle(sources_filter=["test_source"])
        assert report["summary"] == "success"


def test_system_auxiliary_methods(mock_system_components):
    # Setup health
    # Setup health (fixture default)
    system = NewsCollectorSystem()
    system.initialize()

    # Mock DB returns for top articles
    mock_article = MagicMock()
    # Setup properties for Adapter/Contract validation
    mock_article.id = 1
    mock_article.title = "Top Art"
    mock_article.summary = "Summary"
    mock_article.url = "http://example.com"
    mock_article.source_id = "src"
    mock_article.source_name = "Source"
    mock_article.final_score = 0.9
    mock_article.published_date = datetime.now(timezone.utc)
    mock_article.article_metadata = {}
    mock_article.authors = []
    mock_article.category = "tech"
    mock_article.content = None
    mock_article.published_url = None
    mock_article.doi = None
    mock_article.journal = None
    mock_article.published_at = None
    mock_article.collected_date = None
    mock_article.score_components = {}
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
    mock_system_components["db"].get_health_status.return_value = {"status": "healthy"}
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



