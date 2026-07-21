from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from news_collector.collectors.base_collector import create_collector
from news_collector.collectors.dispatcher import CollectorDispatcher


def test_factory_get_collector():
    with patch("news_collector.collectors.rss_collector.RSSCollector") as mock_rss:
        c = create_collector("rss")
        assert c is not None
        mock_rss.assert_called()


def test_factory_invalid_type():
    with pytest.raises(ValueError, match="no soportado"):
        create_collector("unknown_type")


def test_dispatcher_collect_all():
    dispatcher = CollectorDispatcher()
    with patch.object(
        dispatcher, "collect_from_multiple_sources_async", new_callable=AsyncMock
    ) as mock_async:
        mock_async.return_value = {"summary": "done"}
        res = dispatcher.collect_from_multiple_sources({})
        assert res["summary"] == "done"


@pytest.mark.asyncio
async def test_dispatcher_failed_task_attributed_with_source_identity():
    """Failed collector tasks must report source IDs and increment counts."""
    dispatcher = CollectorDispatcher()

    # Register a mock collector that raises
    mock_collector = MagicMock()
    mock_collector.collect_from_multiple_sources_async = AsyncMock(
        side_effect=RuntimeError("connection refused")
    )
    dispatcher.collectors["rss"] = mock_collector

    sources = {"source_a": {"collector_type": "rss"}, "source_b": {"collector_type": "rss"}}

    result = await dispatcher.collect_from_multiple_sources_async(sources)

    assert result["collection_summary"]["errors_encountered"] == 2
    assert result["collection_summary"]["sources_processed"] == 2
    assert "source_a" in result["source_details"]
    assert "source_b" in result["source_details"]
    assert result["source_details"]["source_a"]["success"] is False
    assert "connection refused" in result["source_details"]["source_a"]["error"]


@pytest.mark.asyncio
async def test_dispatcher_partial_failure_mixed_results():
    """One failing and one succeeding task must both be counted."""
    dispatcher = CollectorDispatcher()

    fail_collector = MagicMock()
    fail_collector.collect_from_multiple_sources_async = AsyncMock(
        side_effect=RuntimeError("timeout")
    )
    success_collector = MagicMock()
    success_collector.collect_from_multiple_sources_async = AsyncMock(
        return_value={
            "source_details": {"good_source": {"success": True}},
            "collection_summary": {
                "sources_processed": 1,
                "articles_found": 3,
                "articles_saved": 3,
                "errors_encountered": 0,
            },
        }
    )
    dispatcher.collectors["rss"] = fail_collector
    dispatcher.collectors["html"] = success_collector

    sources = {
        "bad_source": {"collector_type": "rss"},
        "good_source": {"collector_type": "html"},
    }

    result = await dispatcher.collect_from_multiple_sources_async(sources)

    # Failed source counted
    assert result["collection_summary"]["errors_encountered"] == 1
    assert result["collection_summary"]["sources_processed"] == 2
    assert result["source_details"]["bad_source"]["success"] is False

    # Successful source counted
    assert result["source_details"]["good_source"]["success"] is True
    assert result["collection_summary"]["articles_found"] == 3
