#!/usr/bin/env python3
"""Audit the test suite from data: coverage gaps, tests that touch no code, weak tests.

Usage (see ``make test-audit``):
    python scripts/test_suite_audit.py --coverage reports/audit/cov.json \
        [--collected reports/audit/collected.txt] [--tests tests] [--out reports/audit]

``cov.json`` must come from pytest with ``--cov=... --cov-context=test
--cov-report=json:...``; ``collected.txt`` from ``pytest --collect-only -q``.
Read-only over the repo; writes ``test_audit.md`` and ``test_audit.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from news_collector.quality.suite_audit import (  # noqa: E402
    analyze_test_quality,
    contexts_by_test,
    critical_gaps,
    load_coverage,
    render_markdown,
    summarize_packages,
    tests_touching_no_code,
    totals,
)


def _read_collected(path: Path) -> List[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if "::" in line and not line.startswith(("=", " "))
    ]


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--coverage", type=Path, required=True)
    ap.add_argument("--collected", type=Path)
    ap.add_argument("--tests", type=Path, default=Path("tests"))
    ap.add_argument("--out", type=Path, default=Path("reports/audit"))
    ap.add_argument("--threshold", type=float, default=85.0)
    args = ap.parse_args(argv)

    files = load_coverage(args.coverage)
    quality = analyze_test_quality(args.tests)
    no_code: List[str] = []
    if args.collected and args.collected.exists():
        no_code = tests_touching_no_code(
            _read_collected(args.collected), contexts_by_test(args.coverage)
        )

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "test_audit.md").write_text(
        render_markdown(files, quality, no_code, threshold=args.threshold),
        encoding="utf-8",
    )
    tot = totals(files.values())
    (args.out / "test_audit.json").write_text(
        json.dumps(
            {
                "line_rate": round(tot.line_rate, 2),
                "branch_rate": round(tot.branch_rate, 2),
                "packages": [
                    {"name": p.name, "line_rate": round(p.line_rate, 1)}
                    for p in summarize_packages(files)
                ],
                "gaps": [
                    {
                        "file": g.path,
                        "line_rate": round(g.line_rate, 1),
                        "missing": g.missing,
                    }
                    for g in critical_gaps(files, threshold=args.threshold)
                ],
                "no_assertion": quality.no_assertion,
                "mock_heavy": quality.mock_heavy,
                "tests_touching_no_code": no_code,
            },
            indent=1,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(
        f"line {tot.line_rate:.1f}% / branch {tot.branch_rate:.1f}% -> {args.out}/test_audit.md"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
