#!/usr/bin/env python3
"""Run trufflehog3 secret scanning and persist the JSON report."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def build_command(
    *,
    python_bin: Path,
    output: Path,
    severity: str,
    target: Path,
) -> list[str]:
    return [
        str(python_bin),
        "-m",
        "trufflehog3",
        "--format",
        "JSON",
        "--severity",
        severity,
        "--output",
        str(output),
        "--no-history",
        str(target),
    ]


def run_trufflehog3(command: list[str]) -> int:
    result = subprocess.run(command, check=False)  # noqa: S603
    if result.returncode in (0, 1):
        return 0
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination for the JSON report.",
    )
    parser.add_argument(
        "--severity",
        default="HIGH",
        help="Minimum severity to report (LOW, MEDIUM, HIGH).",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path("."),
        help="Directory to scan for secrets.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(".gitleaks.toml"),
        help=(
            "Reserved for compatibility; configuration is applied during gating "
            "rather than at scan time."
        ),
    )
    args = parser.parse_args(argv)

    args.output.parent.mkdir(parents=True, exist_ok=True)

    command = build_command(
        python_bin=Path(sys.executable),
        output=args.output,
        severity=args.severity.upper(),
        target=args.target,
    )

    return run_trufflehog3(command)


if __name__ == "__main__":
    sys.exit(main())
