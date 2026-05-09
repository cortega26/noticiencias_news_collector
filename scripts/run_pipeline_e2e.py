#!/usr/bin/env python3
"""Run a deterministic collector-to-frontend E2E scenario and persist diagnostics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from news_collector.logic.workflows.pipeline_e2e import run_pipeline_e2e_scenario


def _resolve_fixture(value: str) -> Path:
    path = Path(value)
    if path.exists():
        return path.resolve()
    candidate = PROJECT_ROOT / "tests" / "fixtures" / "pipeline_e2e" / f"{value}.json"
    if candidate.exists():
        return candidate.resolve()
    raise FileNotFoundError(f"Unknown E2E fixture: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", help="Scenario file path or fixture stem name")
    parser.add_argument(
        "--bundle-root",
        help="Optional diagnostics bundle directory. Defaults to a temp directory.",
    )
    args = parser.parse_args()

    summary = run_pipeline_e2e_scenario(
        _resolve_fixture(args.scenario),
        bundle_root=args.bundle_root,
    )
    print(json.dumps(summary.model_dump(mode="json"), indent=2))
    return 0 if summary.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
