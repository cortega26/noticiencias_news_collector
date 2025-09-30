#!/usr/bin/env python
"""
Load test for feed adapters.

Runs N sources x 1 fetch each (or more) and reports p50/p95/p99 latencies,
error rate, and a retry histogram. Can use async httpx for concurrency when
--async is passed (or env ASYNC_ENABLED=true).
"""
import argparse
import asyncio
import math
import random
import time
from typing import Dict, Any, List, Tuple

import httpx
import sys
from pathlib import Path

# Ensure project root on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import ALL_SOURCES
from config.settings import COLLECTION_CONFIG, RATE_LIMITING_CONFIG


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    k = (len(values) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return values[int(k)]
    return values[f] * (c - k) + values[c] * (k - f)


def retry_sleep(attempt: int) -> float:
    base = RATE_LIMITING_CONFIG.get("backoff_base", 0.5)
    max_b = RATE_LIMITING_CONFIG.get("backoff_max", 10.0)
    jitter = random.uniform(0, RATE_LIMITING_CONFIG.get("jitter_max", 0.3))
    return min(max_b, (base * (2**attempt)) + jitter)


async def fetch_with_retries(
    client: httpx.AsyncClient, url: str
) -> Tuple[bool, float, int, int]:
    start = time.perf_counter()
    attempts = 0
    status = 0
    max_retries = RATE_LIMITING_CONFIG["max_retries"]
    for attempt in range(0, max_retries + 1):
        attempts += 1
        try:
            r = await client.get(url, timeout=COLLECTION_CONFIG["request_timeout"])
            status = r.status_code
            if r.status_code in (429, 500, 502, 503, 504):
                if attempt < max_retries:
                    await asyncio.sleep(retry_sleep(attempt))
                    continue
                else:
                    break
            r.raise_for_status()
            break
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError):
            if attempt < max_retries:
                await asyncio.sleep(retry_sleep(attempt))
                continue
            else:
                status = 599
                break
    return (
        200 <= status < 400,
        (time.perf_counter() - start) * 1000.0,
        attempts,
        status,
    )


async def run_async(
    sources: Dict[str, Dict[str, Any]], concurrency: int
) -> Dict[str, Any]:
    headers = {"User-Agent": COLLECTION_CONFIG["user_agent"]}
    sem = asyncio.Semaphore(concurrency)
    latencies: List[float] = []
    errors = 0
    retry_hist: Dict[int, int] = {}
    codes: Dict[int, int] = {}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:

        async def one(url: str):
            nonlocal errors
            async with sem:
                ok, ms, attempts, status = await fetch_with_retries(client, url)
                latencies.append(ms)
                retry_hist[attempts] = retry_hist.get(attempts, 0) + 1
                codes[status] = codes.get(status, 0) + 1
                if not ok:
                    errors += 1

        tasks = [one(cfg["url"]) for _, cfg in sources.items()]
        await asyncio.gather(*tasks)

    latencies.sort()
    result = {
        "count": len(latencies),
        "p50_ms": percentile(latencies, 50),
        "p95_ms": percentile(latencies, 95),
        "p99_ms": percentile(latencies, 99),
        "error_rate": (errors / max(1, len(latencies))) * 100.0,
        "retry_hist": retry_hist,
        "status_codes": codes,
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--num-sources", type=int, default=10)
    parser.add_argument("-c", "--concurrency", type=int, default=8)
    parser.add_argument("--async", dest="use_async", action="store_true", default=False)
    args = parser.parse_args()

    # Select N sources
    items = list(ALL_SOURCES.items())[: args.num_sources]
    selected = dict(items)

    print(f"Running load test on {len(selected)} sources | async={args.use_async}")
    if args.use_async or COLLECTION_CONFIG.get("async_enabled"):
        result = asyncio.run(run_async(selected, args.concurrency))
    else:
        # Fallback simple loop using async runner with concurrency=1
        result = asyncio.run(run_async(selected, 1))

    print("\nLatency (ms):")
    print(
        f"  p50={result['p50_ms']:.1f}  p95={result['p95_ms']:.1f}  p99={result['p99_ms']:.1f}"
    )
    print(f"Errors: {result['error_rate']:.2f}%  out of {result['count']}")

    print("\nRetry histogram (attempts -> count):")
    for k in sorted(result["retry_hist"].keys()):
        print(f"  {k}: {result['retry_hist'][k]}")

    print("\nStatus codes:")
    for code in sorted(result["status_codes"].keys()):
        print(f"  {code}: {result['status_codes'][code]}")

    print("\nDone.")


if __name__ == "__main__":
    main()
