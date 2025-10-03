import asyncio
from pathlib import Path
from time import perf_counter
from typing import List

import pytest

from config.settings import COLLECTION_CONFIG
from src.collectors.async_rss_collector import AsyncRSSCollector
from src.collectors.rss_collector import RSSCollector
from src.perf import (
    CollectorReplaySession,
    MemoryFeedStore,
    ReplayEvent,
    load_replay_fixture,
)


pytestmark = pytest.mark.perf


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "perf" / "rss_load_sample.jsonl"
)


@pytest.fixture(scope="module")
def replay_events() -> List[ReplayEvent]:
    return load_replay_fixture(FIXTURE_PATH)


def test_async_collector_outperforms_sync(
    monkeypatch: pytest.MonkeyPatch, replay_events: List[ReplayEvent]
) -> None:
    monkeypatch.setitem(COLLECTION_CONFIG, "max_concurrent_requests", 4)

    sources = CollectorReplaySession(replay_events).build_source_config()

    def run_sync() -> float:
        collector = RSSCollector()
        collector.db_manager = MemoryFeedStore()
        session = CollectorReplaySession(replay_events)
        with session.patch_collector(collector):
            start = perf_counter()
            collector.collect_from_multiple_sources(sources)
            return perf_counter() - start

    async def run_async() -> float:
        collector = AsyncRSSCollector()
        collector.db_manager = MemoryFeedStore()
        session = CollectorReplaySession(replay_events)
        with session.patch_collector(collector, asynchronous=True):
            start = perf_counter()
            await collector.collect_from_multiple_sources_async(sources)
            return perf_counter() - start

    sync_runs = [run_sync() for _ in range(3)]
    async_runs = [asyncio.run(run_async()) for _ in range(3)]

    assert min(async_runs) < min(sync_runs)
    assert sum(async_runs) / len(async_runs) < (sum(sync_runs) / len(sync_runs)) * 0.9
