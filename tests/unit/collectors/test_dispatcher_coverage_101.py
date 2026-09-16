"""Plan 101 coverage backfill: CollectorDispatcher init-failure isolation,
factory/health-tracker propagation, sync-collector fallback and stats.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from noticiencias.config_manager import load_config

from news_collector.collectors.dispatcher import CollectorDispatcher


def test_init_failure_isolated_per_collector():
    """One failing collector must not take down the whole dispatcher."""
    with patch(
        "news_collector.collectors.dispatcher.create_collector",
        side_effect=RuntimeError("nope"),
    ):
        dispatcher = CollectorDispatcher(config=load_config())
    assert dispatcher.collectors == {}
    assert dispatcher.is_healthy()  # vacuous over zero collectors


def test_partial_init_failure_keeps_working_collectors():
    real_create = __import__(
        "news_collector.collectors.base_collector", fromlist=["create_collector"]
    ).create_collector

    def flaky(collector_type, config=None):
        if collector_type == "headless":
            raise RuntimeError("no playwright here")
        return real_create(collector_type, config=config)

    with patch(
        "news_collector.collectors.dispatcher.create_collector", side_effect=flaky
    ):
        dispatcher = CollectorDispatcher(config=load_config())
    assert "headless" not in dispatcher.collectors
    assert "rss" in dispatcher.collectors


def test_set_logger_factory_propagates_to_collectors():
    dispatcher = CollectorDispatcher(config=load_config())
    assert dispatcher.collectors, "expected real collectors in test env"
    factory = MagicMock()
    dispatcher.set_logger_factory(factory)
    assert dispatcher.logger_factory is factory


def test_set_health_tracker_propagates_to_collectors():
    dispatcher = CollectorDispatcher(config=load_config())
    tracker = MagicMock()
    dispatcher.set_health_tracker(tracker)
    assert dispatcher.health_tracker is tracker


def test_set_health_tracker_tolerates_tracker_less_collectors():
    dispatcher = CollectorDispatcher(config=load_config())
    dispatcher.collectors = {"plain": SimpleNamespace()}
    dispatcher.set_health_tracker(MagicMock())  # must not raise
    dispatcher.set_logger_factory(MagicMock())  # must not raise


@pytest.mark.asyncio
async def test_sync_only_collector_runs_via_thread_fallback():
    dispatcher = CollectorDispatcher(config=load_config())
    sync_collector = SimpleNamespace(
        collect_from_multiple_sources=MagicMock(
            return_value={
                "source_details": {"s1": {"success": True}},
                "collection_summary": {
                    "articles_found": 1,
                    "articles_saved": 1,
                    "errors_encountered": 0,
                },
            }
        )
    )
    dispatcher.collectors = {"rss": sync_collector}
    result = await dispatcher.collect_from_multiple_sources_async(
        {"s1": {"collector_type": "rss"}}
    )
    assert result["collection_summary"]["sources_succeeded"] == 1
    sync_collector.collect_from_multiple_sources.assert_called_once()


@pytest.mark.asyncio
async def test_close_handles_sync_and_async_collectors():
    dispatcher = CollectorDispatcher(config=load_config())
    async_collector = SimpleNamespace(close=AsyncMock())
    sync_collector = SimpleNamespace(close=MagicMock())
    dispatcher.collectors = {"a": async_collector, "b": sync_collector}
    await dispatcher.close()
    async_collector.close.assert_awaited_once()
    sync_collector.close.assert_called_once()


def test_get_stats_aggregates_collectors():
    dispatcher = CollectorDispatcher(config=load_config())
    dispatcher.collectors = {
        "rss": SimpleNamespace(get_stats=lambda: {"ok": True}),
    }
    assert dispatcher.get_stats() == {"rss": {"ok": True}}
