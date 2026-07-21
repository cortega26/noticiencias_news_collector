#!/usr/bin/env python
"""Benchmark for plan 038, Step 3: enrichment_metrics_store batching.

Generates N deterministic attempt/success/failure/cost events across a
handful of sources, replays them through both an immediate (commit-per-event)
store and a batched store, and asserts:

  1. The batched store's total commit count stays within --max-commits.
  2. Every final aggregate row is byte-identical between the two stores —
     the perf win must never come at the cost of correctness (see
     plans/038/spec.md for why "coalesce sum/count" would silently produce
     wrong averages here).

Usage:
    python scripts/benchmark_metrics.py --events 1000 --max-commits 25
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from news_collector.observability.enrichment_metrics_store import (  # noqa: E402
    EnrichmentMetricsStore,
)

_STRATEGIES = [
    "http",
    "scrapling_http",
    "headless",
    "scrapling_stealth",
    "proxy",
    "scholarly",
]
_SOURCES = [f"source_{i}" for i in range(10)]


def _generate_events(count: int, seed: int = 1337) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    events: list[dict[str, Any]] = []
    for _ in range(count):
        source_id = rng.choice(_SOURCES)
        strategy = rng.choice(_STRATEGIES)
        kind = rng.choices(
            ["attempt", "success", "failure", "cost"], weights=[40, 30, 20, 10], k=1
        )[0]
        event: dict[str, Any]
        if kind == "attempt":
            event = {"kind": "attempt", "source_id": source_id, "strategy": strategy}
        elif kind == "success":
            event = {
                "kind": "success",
                "source_id": source_id,
                "strategy": strategy,
                "duration": round(rng.uniform(0.1, 5.0), 3),
                "content_length": rng.randint(100, 5000),
                "is_publishable": rng.random() > 0.3,
            }
        elif kind == "failure":
            event = {
                "kind": "failure",
                "source_id": source_id,
                "strategy": strategy,
                "reason": "synthetic_benchmark_failure",
                "duration": round(rng.uniform(0.1, 2.0), 3),
            }
        else:
            event = {
                "kind": "cost",
                "source_id": source_id,
                "proxy_requests": rng.randint(0, 3),
                "headless_seconds": round(rng.uniform(0.0, 2.0), 3),
            }
        events.append(event)
    return events


def _replay(store: EnrichmentMetricsStore, events: list[dict[str, Any]]) -> None:
    for event in events:
        if event["kind"] == "attempt":
            store.record_attempt(event["source_id"], strategy=event["strategy"])
        elif event["kind"] == "success":
            store.record_success(
                event["source_id"],
                event["strategy"],
                duration=event["duration"],
                content_length=event["content_length"],
                is_publishable=event["is_publishable"],
            )
        elif event["kind"] == "failure":
            store.record_failure(
                event["source_id"],
                event["strategy"],
                reason=event["reason"],
                duration=event["duration"],
            )
        else:
            store.record_cost(
                event["source_id"],
                proxy_requests=event["proxy_requests"],
                headless_seconds=event["headless_seconds"],
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, default=1000)
    parser.add_argument("--max-commits", type=int, default=25)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=40,
        help="Matches the batch size wired into base_collector.py's collection cycle.",
    )
    args = parser.parse_args()

    events = _generate_events(args.events)
    tmpdir = tempfile.mkdtemp(prefix="benchmark_metrics_")

    immediate = EnrichmentMetricsStore.create_isolated(
        environment="benchmark",
        db_path=str(Path(tmpdir) / "immediate.db"),
        flush_batch_size=1,
    )
    batched = EnrichmentMetricsStore.create_isolated(
        environment="benchmark",
        db_path=str(Path(tmpdir) / "batched.db"),
        flush_batch_size=args.batch_size,
    )

    try:
        start = time.perf_counter()
        _replay(immediate, events)
        immediate_elapsed = time.perf_counter() - start

        start = time.perf_counter()
        _replay(batched, events)
        batched.flush()
        batched_elapsed = time.perf_counter() - start

        immediate_all = immediate.get_all_metrics()
        batched_all = batched.get_all_metrics()

        def _without_timestamp(row):
            if row is None:
                return None
            return {k: v for k, v in row.items() if k != "last_updated"}

        mismatches = []
        for source_id in set(immediate_all) | set(batched_all):
            left = _without_timestamp(immediate_all.get(source_id))
            right = _without_timestamp(batched_all.get(source_id))
            if left != right:
                mismatches.append((source_id, left, right))

        print(f"[benchmark_metrics] events={args.events} batch_size={args.batch_size}")
        print(
            f"[benchmark_metrics] immediate commits={immediate.flush_count} "
            f"({immediate_elapsed:.3f}s)"
        )
        print(
            f"[benchmark_metrics] batched commits={batched.flush_count} "
            f"({batched_elapsed:.3f}s)"
        )
        print(f"[benchmark_metrics] sources touched={len(immediate_all)}")

        ok = True
        if batched.flush_count > args.max_commits:
            print(
                f"[benchmark_metrics] FAIL: {batched.flush_count} commits "
                f"exceeds --max-commits {args.max_commits}"
            )
            ok = False

        if mismatches:
            print(
                f"[benchmark_metrics] FAIL: {len(mismatches)} source(s) diverged "
                f"between immediate and batched flush:"
            )
            for source_id, left, right in mismatches[:5]:
                print(f"  {source_id}: immediate={left} batched={right}")
            ok = False

        if ok:
            print("[benchmark_metrics] PASS: commits bounded, aggregates identical.")
        return 0 if ok else 1
    finally:
        immediate.close()
        batched.close()


if __name__ == "__main__":
    sys.exit(main())
