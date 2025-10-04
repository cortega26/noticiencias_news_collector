"""Profile synchronous vs asynchronous collectors using replay fixtures."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from collections import Counter
from pathlib import Path
from statistics import mean
from time import perf_counter, process_time
from typing import Iterable, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import COLLECTION_CONFIG

from src.collectors.async_rss_collector import AsyncRSSCollector
from src.collectors.rss_collector import RSSCollector
from src.perf import (
    CollectorReplaySession,
    MemoryFeedStore,
    ReplayEvent,
    load_replay_fixture,
)


def _percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    k = (len(sorted_values) - 1) * (percentile / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def _summarize_requests(
    requests: Iterable[dict[str, float | int]],
) -> dict[str, object]:
    records = list(requests)
    if not records:
        return {
            "avg_latency_ms": 0.0,
            "p50_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "status_counts": {},
        }
    latencies = [float(entry["latency_ms"]) for entry in records]
    statuses = Counter(int(entry["status_code"]) for entry in records)
    return {
        "avg_latency_ms": mean(latencies),
        "p50_latency_ms": _percentile(latencies, 50.0),
        "p95_latency_ms": _percentile(latencies, 95.0),
        "status_counts": dict(sorted(statuses.items())),
    }


def _run_sync(
    events: List[ReplayEvent], sources: dict[str, dict[str, object]]
) -> dict[str, object]:
    collector = RSSCollector()
    collector.db_manager = MemoryFeedStore()
    session = CollectorReplaySession(events)
    with session.patch_collector(collector):
        start_cpu = process_time()
        start = perf_counter()
        collector.collect_from_multiple_sources(sources)
        duration = perf_counter() - start
        cpu_time = process_time() - start_cpu
    summary = _summarize_requests(session.requests)
    summary.update(
        {
            "duration_s": duration,
            "articles": len(collector.db_manager.saved_articles),
            "requests": len(session.requests),
            "cpu_time_s": cpu_time,
        }
    )
    return summary


async def _run_async(
    events: List[ReplayEvent],
    sources: dict[str, dict[str, object]],
    concurrency: int,
) -> dict[str, object]:
    collector = AsyncRSSCollector()
    collector.db_manager = MemoryFeedStore()
    session = CollectorReplaySession(events)
    original_concurrency = COLLECTION_CONFIG.get("max_concurrent_requests", 8)
    COLLECTION_CONFIG["max_concurrent_requests"] = concurrency
    try:
        with session.patch_collector(collector, asynchronous=True):
            start_cpu = process_time()
            start = perf_counter()
            await collector.collect_from_multiple_sources_async(sources)
            duration = perf_counter() - start
            cpu_time = process_time() - start_cpu
    finally:
        COLLECTION_CONFIG["max_concurrent_requests"] = original_concurrency
    summary = _summarize_requests(session.requests)
    summary.update(
        {
            "duration_s": duration,
            "articles": len(collector.db_manager.saved_articles),
            "requests": len(session.requests),
            "concurrency": concurrency,
            "cpu_time_s": cpu_time,
        }
    )
    return summary


def _format_duration(seconds: float) -> str:
    return f"{seconds * 1000:.1f} ms"


def _format_throughput(articles: int, seconds: float) -> str:
    if seconds <= 0:
        return "∞"
    return f"{articles / seconds:.1f} items/s"


def profile_collectors(
    fixture: Path, concurrency_levels: List[int]
) -> dict[str, object]:
    events = load_replay_fixture(fixture)
    sources = CollectorReplaySession(events).build_source_config()

    sync_metrics = _run_sync(events, sources)

    async_metrics: List[dict[str, object]] = []
    for level in concurrency_levels:
        metrics = asyncio.run(_run_async(events, sources, level))
        async_metrics.append(metrics)

    return {"sync": sync_metrics, "async": async_metrics}


def _print_report(results: dict[str, object]) -> None:
    sync_metrics = results["sync"]
    print("== Sync baseline ==")
    print(
        f"duration: {_format_duration(sync_metrics['duration_s'])}  "
        f"throughput: {_format_throughput(sync_metrics['articles'], sync_metrics['duration_s'])}  "
        f"requests: {sync_metrics['requests']}"
    )
    print(
        "avg latency: {avg:.1f} ms  p50: {p50:.1f} ms  p95: {p95:.1f} ms  "
        "statuses: {statuses}".format(
            avg=sync_metrics["avg_latency_ms"],
            p50=sync_metrics["p50_latency_ms"],
            p95=sync_metrics["p95_latency_ms"],
            statuses=sync_metrics["status_counts"],
        )
    )
    print(
        "cpu: {cpu:.3f}s  io-wait: {io:.3f}s".format(
            cpu=sync_metrics["cpu_time_s"],
            io=max(sync_metrics["duration_s"] - sync_metrics["cpu_time_s"], 0.0),
        )
    )

    print("\n== Async sweep ==")
    header = "concurrency | duration | throughput | speedup | p50 | p95 | cpu"
    print(header)
    print("-" * len(header))
    baseline = sync_metrics["duration_s"]
    for metrics in results["async"]:
        duration = metrics["duration_s"]
        speedup = baseline / duration if duration else float("inf")
        print(
            f"{metrics['concurrency']:>11} | {_format_duration(duration):>9} | "
            f"{_format_throughput(metrics['articles'], duration):>11} | {speedup:>6.2f}x | "
            f"{metrics['p50_latency_ms']:>5.1f} | {metrics['p95_latency_ms']:>5.1f} | "
            f"{metrics['cpu_time_s']:.3f}s"
        )
    print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("tests/data/perf/rss_load_sample.jsonl"),
        help="Path to JSONL fixture with replay events.",
    )
    parser.add_argument(
        "--concurrency",
        default="1,2,4,8",
        help="Comma-separated list of concurrency levels for async sweep.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write JSON results.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    levels = [int(item) for item in args.concurrency.split(",") if item.strip()]
    if not levels:
        raise SystemExit("At least one concurrency level is required")
    results = profile_collectors(args.fixture, levels)
    _print_report(results)
    if args.output:
        args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
