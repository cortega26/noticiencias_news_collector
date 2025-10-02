#!/usr/bin/env python3
"""Utility script to bump the project semantic version."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Final, Tuple

VERSION_FILE: Final[Path] = Path("config") / "version.py"
PROJECT_VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r'^(?P<prefix>PROJECT_VERSION\s*:\s*Final\[str\]\s*=\s*")'
    r'(?P<version>[^"\n]+)'
    r'(?P<suffix>"\s*)$'
)
SEMVER_RE: Final[re.Pattern[str]] = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
)


class VersionBumpError(RuntimeError):
    """Raised when the version cannot be bumped automatically."""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bump the project version in config/version.py",
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


def read_current_version() -> Tuple[str, list[str]]:
    lines = VERSION_FILE.read_text(encoding="utf-8").splitlines()
    for line in lines:
        match = PROJECT_VERSION_PATTERN.match(line.strip())
        if match:
            return match.group("version"), lines
    raise VersionBumpError(
        "PROJECT_VERSION declaration not found in config/version.py",
    )


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


def write_version(lines: list[str], new_version: str) -> None:
    updated_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        match = PROJECT_VERSION_PATTERN.match(stripped)
        if match:
            updated_line = (
                f"{match.group('prefix')}{new_version}{match.group('suffix')}"
            )
            leading = line[: len(line) - len(stripped)]
            updated_lines.append(f"{leading}{updated_line}")
        else:
            updated_lines.append(line)
    VERSION_FILE.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        current_version, lines = read_current_version()
        new_version = compute_next_version(
            current_version,
            part=args.part,
            explicit=args.explicit_version,
        )
        if args.dry_run:
            print(new_version)
            return 0
        write_version(lines, new_version)
        print(new_version)
        return 0
    except VersionBumpError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
