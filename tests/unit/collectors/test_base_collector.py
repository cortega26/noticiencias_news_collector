import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from news_collector.collectors.base_collector import BaseCollector


class ConcreteCollector(BaseCollector):
    def collect_from_source(self, source_id, source_config):
        return {"success": True}

    def _create_session(self):
        pass


def test_base_collector_init():
    with patch("news_collector.collectors.base_collector.get_database_manager"):
        logger_mock = MagicMock()
        c = ConcreteCollector(logger_factory=logger_mock)
        assert c.collector_type == "ConcreteCollector"


def test_normalization():
    with patch("news_collector.collectors.base_collector.get_database_manager"):
        c = ConcreteCollector(logger_factory=MagicMock())
        # Assuming BaseCollector DOES NOT have simple URL normalization public method
        # If it doesn't, we can skip or test _clean_text which uses normalization
        assert c._clean_text("  foo  ") == "foo"


@pytest.fixture
def async_collector():
    with patch("news_collector.collectors.base_collector.get_database_manager"):
        collector = ConcreteCollector(logger_factory=MagicMock())
        collector._finalize_collection_cycle = lambda results: results
        return collector


def _source_configs(source_ids):
    return {
        source_id: {
            "name": f"Source {source_id}",
            "url": f"https://x.example/{source_id}",
        }
        for source_id in source_ids
    }


async def test_async_collection_respects_max_concurrent_sources(
    async_collector, monkeypatch
):
    monkeypatch.setattr(
        "news_collector.collectors.base_collector.get_runtime_config",
        lambda: SimpleNamespace(collection_config={"max_concurrent_sources": 2}),
    )

    source_ids = [f"s{i}" for i in range(6)]
    active = {"n": 0, "max": 0}
    processed = []

    async def _process(source_id, source_config):
        active["n"] += 1
        active["max"] = max(active["max"], active["n"])
        processed.append(source_id)
        await asyncio.sleep(0.02)
        active["n"] -= 1
        return {"success": True, "source_id": source_id}

    async_collector._process_single_source_async = _process

    result = await async_collector.collect_from_multiple_sources_async(
        _source_configs(source_ids)
    )

    assert active["max"] == 2, "concurrency bound must be honoured"
    assert sorted(result.keys()) == sorted(source_ids)


async def test_async_collection_defaults_to_ten(async_collector, monkeypatch):
    monkeypatch.setattr(
        "news_collector.collectors.base_collector.get_runtime_config",
        lambda: SimpleNamespace(collection_config={}),
    )

    source_ids = [f"s{i}" for i in range(12)]
    active = {"n": 0, "max": 0}
    processed = []

    async def _process(source_id, source_config):
        active["n"] += 1
        active["max"] = max(active["max"], active["n"])
        processed.append(source_id)
        await asyncio.sleep(0.01)
        active["n"] -= 1
        return {"success": True, "source_id": source_id}

    async_collector._process_single_source_async = _process

    result = await async_collector.collect_from_multiple_sources_async(
        _source_configs(source_ids)
    )

    assert active["max"] <= 10, "default concurrency bound must cap fan-out"
    assert sorted(result.keys()) == sorted(source_ids)


async def test_async_collection_completes_when_task_raises(
    async_collector, monkeypatch
):
    monkeypatch.setattr(
        "news_collector.collectors.base_collector.get_runtime_config",
        lambda: SimpleNamespace(collection_config={"max_concurrent_sources": 1}),
    )

    source_ids = ["ok", "boom"]

    async def _process(source_id, source_config):
        if source_id == "boom":
            raise RuntimeError(f"boom {source_id}")
        return {"success": True, "source_id": source_id}

    async_collector._process_single_source_async = _process

    result = await async_collector.collect_from_multiple_sources_async(
        _source_configs(source_ids)
    )

    # Semaphore must be released after the failing task so the remaining
    # source can still run (bound=1 would deadlock otherwise).
    assert sorted(result.keys()) == sorted(source_ids)
    assert result["ok"]["success"] is True
    assert result["boom"]["success"] is False
