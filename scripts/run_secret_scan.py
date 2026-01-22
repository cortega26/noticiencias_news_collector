#!/usr/bin/env python3
"""Helper CLI to run secret scans with explicit configuration."""

import argparse
import sys
from pathlib import Path
from typing import List


def _severity_choice(value: str) -> str:
    valid = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    upper_val = value.upper()
    if upper_val not in valid:
        raise argparse.ArgumentTypeError(f"Invalid severity: {value}. Must be one of {valid}")
    return upper_val


def _ensure_directory(path: str | Path) -> Path:
    p = Path(path)
    if not p.exists():
        raise argparse.ArgumentTypeError(f"Directory does not exist: {path}")
    if not p.is_dir():
        raise argparse.ArgumentTypeError(f"Path is not a directory: {path}")
    return p.resolve()


def build_command(
    python_bin: Path, output: Path, severity: str, target: Path
) -> List[str]:
    return [
        str(python_bin),
        "-m",
        "trufflehog3",
        "--format",
        "json",
        "--output",
        str(output),
        "--no-history",
        str(target),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run trufflehog3 wrapper.")
    parser.add_argument("--output", type=Path, required=True, help="Path to output JSON report.")
    parser.add_argument("--severity", type=_severity_choice, default="HIGH", help="Minimum severity (unused in runner, kept for compat).")
    parser.add_argument("target", type=_ensure_directory, help="Target directory to scan.")

    args = parser.parse_args()

    cmd = build_command(
        python_bin=Path(sys.executable),
        output=args.output,
        severity=args.severity,
        target=args.target,
    )

    # We import subprocess only when running, to keep top-level side-effects low
    import subprocess
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        return e.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
