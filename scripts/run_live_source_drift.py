#!/usr/bin/env python3
"""Run a live critical-cohort collection sweep and emit a differential drift report."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from news_collector.diagnostics import SourceHealthTracker
from news_collector.logic.workflows.live_source_drift import (
    CRITICAL_SOURCE_COHORT,
    build_live_source_drift_report,
    load_source_health_file,
    render_live_source_drift_markdown,
)
from news_collector.system import create_system


def _default_bundle_dir() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return PROJECT_ROOT / "data" / "exports" / "live_source_drift" / timestamp


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sources",
        nargs="+",
        default=CRITICAL_SOURCE_COHORT,
        help="Source IDs to monitor. Defaults to the critical cohort.",
    )
    parser.add_argument(
        "--bundle-dir",
        type=Path,
        default=_default_bundle_dir(),
        help="Directory where artifacts and reports will be written.",
    )
    parser.add_argument(
        "--baseline-health",
        type=Path,
        default=PROJECT_ROOT / "data" / "exports" / "source_health.json",
        help="Baseline source health snapshot to diff against.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    bundle_dir = args.bundle_dir.resolve()
    bundle_dir.mkdir(parents=True, exist_ok=True)

    baseline_records = load_source_health_file(args.baseline_health)
    if args.baseline_health.exists():
        shutil.copy2(args.baseline_health, bundle_dir / "baseline_source_health.json")

    tracker = SourceHealthTracker()
    system = create_system(health_tracker=tracker)
    if not system.initialize():
        raise RuntimeError(
            "Failed to initialize News Collector System for live drift run."
        )

    try:
        results = asyncio.run(
            system.run_collection_cycle(
                sources_filter=list(args.sources),
                dry_run=False,
            )
        )
    finally:
        system.shutdown()

    current_health_path = PROJECT_ROOT / "data" / "exports" / "source_health.json"
    current_records = load_source_health_file(current_health_path)
    current_copy_path = bundle_dir / "current_source_health.json"
    if current_health_path.exists():
        shutil.copy2(current_health_path, current_copy_path)

    report = build_live_source_drift_report(
        current_records=current_records,
        baseline_records=baseline_records,
        monitored_sources=args.sources,
    )
    report["collection_summary"] = results.get("collection_summary", {})
    report["current_source_health_path"] = str(current_copy_path)
    report["baseline_source_health_path"] = (
        str(bundle_dir / "baseline_source_health.json")
        if (bundle_dir / "baseline_source_health.json").exists()
        else None
    )

    report_path = bundle_dir / "live_source_drift_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    markdown_path = bundle_dir / "live_source_drift_report.md"
    markdown_path.write_text(
        render_live_source_drift_markdown(report),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {"report_path": str(report_path), "markdown_path": str(markdown_path)},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
