#!/usr/bin/env python3
"""Automate changelog updates during tagged releases."""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Final

CHANGELOG_PATH: Final[Path] = Path("CHANGELOG.md")
UNRELEASED_HEADER: Final[str] = "## [Unreleased]"
HEADING_PATTERN: Final[re.Pattern[str]] = re.compile(r"^(?P<hashes>#+)(?P<text>\s.*)$")


class ChangelogUpdateError(RuntimeError):
    """Raised when the changelog cannot be updated."""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update CHANGELOG.md with release notes"
    )
    parser.add_argument(
        "--version", required=True, help="Release version without the leading 'v'"
    )
    parser.add_argument(
        "--notes-file",
        required=True,
        help="Path to a file containing release notes (Markdown).",
    )
    return parser.parse_args(argv)


def ensure_semver(version: str) -> None:
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version):
        raise ChangelogUpdateError(f"Version '{version}' is not a valid SemVer string")


def read_release_notes(path: Path) -> str:
    if not path.exists():
        raise ChangelogUpdateError(f"Release notes file '{path}' not found")
    return path.read_text(encoding="utf-8").strip()


def adjust_markdown_headings(notes: str) -> str:
    adjusted_lines: list[str] = []
    for line in notes.splitlines():
        match = HEADING_PATTERN.match(line.lstrip())
        if match and len(match.group("hashes")) >= 2:
            leading_spaces = " " * (len(line) - len(line.lstrip()))
            new_hashes = "#" * (len(match.group("hashes")) + 1)
            adjusted_lines.append(f"{leading_spaces}{new_hashes}{match.group('text')}")
        else:
            adjusted_lines.append(line)
    return "\n".join(adjusted_lines).strip()


def extract_unreleased_block(changelog_text: str) -> tuple[str, str, str]:
    if UNRELEASED_HEADER not in changelog_text:
        raise ChangelogUpdateError(
            "CHANGELOG.md must include an '## [Unreleased]' heading"
        )
    start_index = changelog_text.index(UNRELEASED_HEADER)
    after_header = start_index + len(UNRELEASED_HEADER)
    next_release_index = changelog_text.find("\n## [", after_header)
    if next_release_index == -1:
        next_release_index = len(changelog_text)
    prefix = changelog_text[:after_header]
    unreleased_content = changelog_text[after_header:next_release_index]
    suffix = changelog_text[next_release_index:]
    return prefix, unreleased_content, suffix


def build_release_block(version: str, unreleased: str, release_notes: str) -> str:
    today = dt.date.today().isoformat()
    sections: list[str] = []
    if unreleased.strip():
        sections.append(unreleased.strip())
    if release_notes.strip():
        sections.append(adjust_markdown_headings(release_notes))
    body = "\n\n".join(section.rstrip() for section in sections if section)
    return f"\n\n## [{version}] - {today}\n\n{body}\n"


def update_changelog(version: str, release_notes_path: Path) -> None:
    ensure_semver(version)
    changelog_text = CHANGELOG_PATH.read_text(encoding="utf-8")
    release_notes = read_release_notes(release_notes_path)
    prefix, unreleased_content, suffix = extract_unreleased_block(changelog_text)
    release_block = build_release_block(version, unreleased_content, release_notes)
    placeholder = "\n\n### Added\n- _Pending release notes_\n"
    cleaned_suffix = suffix.lstrip("\n")
    updated = f"{prefix}{placeholder}{release_block}{cleaned_suffix}"
    if not updated.endswith("\n"):
        updated += "\n"
    CHANGELOG_PATH.write_text(updated, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        update_changelog(args.version, Path(args.notes_file))
    except ChangelogUpdateError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
