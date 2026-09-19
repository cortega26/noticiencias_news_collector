#!/usr/bin/env python3
"""Report how each LLM provider has behaved, from persisted attempt metrics.

Usage:
    python scripts/llm_health_report.py [--days 7] [--by-purpose] [--json]
    python scripts/llm_health_report.py --probe     # live check of each provider

Reads ``data/metrics/<env>/llm_metrics.db`` (written by the provider chain).
Use it to decide chain order: providers with high blank/timeout rates or that
are frequently skipped should move down; providers with many ``saves`` are
earning their place.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, List

from news_collector.observability.llm_metrics_store import (
    LLMMetricsStore,
    format_report,
)


def _probe() -> int:
    from news_collector.infrastructure.llm.attempts import provider_name
    from news_collector.infrastructure.llm.factory import get_provider

    chain = get_provider(purpose="probe")
    providers: List[Any] = getattr(chain, "providers", [chain])
    exit_code = 0
    for provider in providers:
        started = time.monotonic()
        try:
            ok, status = provider.check_health(5.0)
        except Exception as err:  # noqa: BLE001 - a probe reports, never crashes
            ok, status = False, f"{type(err).__name__}: {err}"
        elapsed = time.monotonic() - started
        exit_code |= 0 if ok else 1
        print(
            f"{'OK ' if ok else 'FAIL'} {provider_name(provider):<14}"
            f"{str(getattr(provider, 'model', '-')):<40}{elapsed:5.1f}s  {status}"
        )
    return exit_code


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=float, default=7.0, help="window (default 7)")
    parser.add_argument("--db", help="path to llm_metrics.db (default: env DB)")
    parser.add_argument("--by-purpose", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--probe", action="store_true", help="live health probe")
    args = parser.parse_args(argv)

    if args.probe:
        return _probe()

    store = LLMMetricsStore(args.db)
    rows = store.summary(
        since_ts=time.time() - args.days * 86400, by_purpose=args.by_purpose
    )
    if args.as_json:
        print(json.dumps([r.as_dict() for r in rows], indent=2))
    else:
        print(f"LLM provider report — last {args.days:g} day(s) — {store.db_path}\n")
        print(format_report(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
