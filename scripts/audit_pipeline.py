#!/usr/bin/env python3
"""
Unified audit pipeline — reliability sweep, diagnostics, and blacklist report.

Usage:
    python scripts/audit_pipeline.py --sweep            # Phase 1: reliability sweep
    python scripts/audit_pipeline.py --blacklist-report  # Phase 3: blacklist suggestions
    python scripts/audit_pipeline.py --report            # Phase 4: full audit report
    python scripts/audit_pipeline.py --all               # full pipeline
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

AUDIT_DIR = PROJECT_ROOT / "data" / "audit"


def ensure_audit_dir() -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    return AUDIT_DIR


def cmd_sweep(args: argparse.Namespace) -> int:
    """Run the real-network reliability sweep (pytest)."""
    print("=" * 60)
    print(" Phase 1: Source Reliability Sweep")
    print("=" * 60)

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/audit/test_source_reliability_sweep.py",
        "-v",
        "-s",
        "--timeout=3600",
        "--no-header",
        "-p",
        "no:cov",  # skip coverage for speed
        "-o",
        "addopts=",  # clear --cov from pyproject.toml to avoid unknown-arg errors
    ]

    if getattr(args, "sources", None):
        for s in args.sources:
            cmd.extend(["-k", s])

    env = os.environ.copy()
    env["NOTICIENCIAS_AUDIT"] = "true"
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env)
    return result.returncode


def cmd_blacklist_report(args: argparse.Namespace) -> int:
    """Run blacklist suggestions from DB."""
    print("=" * 60)
    print(" Phase 3: Blacklist Candidates Report")
    print("=" * 60)

    result = subprocess.run(
        [sys.executable, "scripts/audit_sources.py", "suggest-blacklist"],
        cwd=str(PROJECT_ROOT),
    )
    return result.returncode


def cmd_report(args: argparse.Namespace) -> int:
    """Generate full audit markdown report."""
    print("=" * 60)
    print(" Phase 4: Full Audit Report")
    print("=" * 60)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = ensure_audit_dir() / f"audit_report_{timestamp}.md"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/audit_sources.py",
            "report",
            "--output",
            str(out_path),
        ],
        cwd=str(PROJECT_ROOT),
    )
    return result.returncode


def cmd_all(args: argparse.Namespace) -> int:
    """Run full audit pipeline."""
    exit_code = 0

    # Phase 1: Sweep
    sweep_args = argparse.Namespace(sources=None)
    if cmd_sweep(sweep_args) != 0:
        print("⚠️  Sweep completed with failures (this is expected for some sources)")
        exit_code = 1

    # Phase 3: Blacklist suggestions
    # Phase 4: Full report
    # Aggregate sub-phase exit codes (both return int) so failures propagate.
    exit_code = max(exit_code, cmd_blacklist_report(args), cmd_report(args))

    print("\n✅ Full audit pipeline completed.")
    if exit_code:
        print("Some sources are non-working. See report for details.")
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified audit pipeline CLI")
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Run reliability sweep (phase 1)",
    )
    parser.add_argument(
        "--blacklist-report",
        action="store_true",
        help="Show blacklist candidates (phase 3)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate full audit markdown report (phase 4)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="run_all",
        help="Run full audit pipeline",
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        help="Filter to specific sources (only for --sweep)",
    )

    args = parser.parse_args()

    if args.run_all:
        return cmd_all(args)
    if args.sweep:
        return cmd_sweep(args)
    if args.blacklist_report:
        return cmd_blacklist_report(args)
    if args.report:
        return cmd_report(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
