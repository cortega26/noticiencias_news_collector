#!/usr/bin/env python3
"""Utility script to bump the project semantic version in news_collector/config/VERSION."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Final, Tuple

# Authoritative source is the flat VERSION file
VERSION_FILE: Final[Path] = Path("news_collector") / "config" / "VERSION"

SEMVER_RE: Final[re.Pattern[str]] = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
)


class VersionBumpError(RuntimeError):
    """Raised when the version cannot be bumped automatically."""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bump the project version in news_collector/config/VERSION",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--part",
        choices=("major", "minor", "patch"),
        help="Which semantic version component to increment.",
    )
    group.add_argument(
        "--set",
        dest="explicit_version",
        metavar="X.Y.Z",
        help="Set an explicit semantic version.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the computed version without writing changes.",
    )
    return parser.parse_args(argv)


def read_current_version() -> str:
    if not VERSION_FILE.exists():
        raise VersionBumpError(f"VERSION file not found at {VERSION_FILE}")

    # Read first line, strip whitespace
    content = VERSION_FILE.read_text(encoding="utf-8").strip()
    # Simple validation
    if not SEMVER_RE.match(content):
        raise VersionBumpError(f"Invalid current version format in file: {content}")
    return content


def validate_semver(version: str) -> Tuple[int, int, int]:
    match = SEMVER_RE.fullmatch(version)
    if not match:
        raise VersionBumpError(f"Invalid semantic version: {version}")
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def compute_next_version(current: str, part: str | None, explicit: str | None) -> str:
    if explicit:
        validate_semver(explicit)
        return explicit
    if part is None:
        raise VersionBumpError("Either --part or --set must be supplied")
    major, minor, patch = validate_semver(current)
    if part == "major":
        major += 1
        minor = 0
        patch = 0
    elif part == "minor":
        minor += 1
        patch = 0
    else:
        patch += 1
    return f"{major}.{minor}.{patch}"


def write_version(new_version: str) -> None:
    # Write only the clean version string
    VERSION_FILE.write_text(f"{new_version}\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        current_version = read_current_version()
        new_version = compute_next_version(
            current_version,
            part=args.part,
            explicit=args.explicit_version,
        )
        if args.dry_run:
            print(new_version)
            return 0
        write_version(new_version)
        print(new_version)
        return 0
    except (VersionBumpError, FileNotFoundError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
