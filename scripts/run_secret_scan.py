#!/usr/bin/env python3
"""Run trufflehog3 secret scanning and persist the JSON report."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ALLOWED_SEVERITIES: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def _severity_choice(value: str) -> str:
    """Validate and normalize the requested severity level."""

    normalized = value.strip().upper()
    if normalized not in ALLOWED_SEVERITIES:
        allowed = ", ".join(ALLOWED_SEVERITIES)
        raise argparse.ArgumentTypeError(
            f"Invalid severity '{value}'. Choose one of: {allowed}."
        )
    return normalized


def _ensure_directory(path: Path) -> Path:
    """Resolve and validate that the provided path is an existing directory."""

    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise argparse.ArgumentTypeError(f"Target path '{path}' does not exist.")
    if not resolved.is_dir():
        raise argparse.ArgumentTypeError(
            f"Target path '{path}' must reference a directory."
        )
    return resolved


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
        type=_severity_choice,
        default="HIGH",
        help="Minimum severity to report (LOW, MEDIUM, HIGH, CRITICAL).",
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

    output_path = args.output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        target = _ensure_directory(args.target)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    command = build_command(
        python_bin=Path(sys.executable),
        output=output_path,
        severity=args.severity,
        target=target,
    )

    return run_trufflehog3(command)


if __name__ == "__main__":
    sys.exit(main())
