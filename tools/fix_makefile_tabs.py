"""Normalize Makefile indentation to ensure recipes start with tabs."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from tools.check_makefile_tabs import TabViolation, find_tab_violations

DEFAULT_TAB_SIZE = 8


@dataclass(frozen=True)
class FixSummary:
    """Structured information about fixes applied to a file."""

    path: Path
    lines: tuple[int, ...]

    def to_json(self) -> str:
        """Return a JSON representation compatible with CI tooling."""

        payload = {
            "path": self.path.as_posix(),
            "lines": list(self.lines),
        }
        return json.dumps(payload, ensure_ascii=False)


def _convert_line(line: str, tab_size: int) -> tuple[str, bool]:
    """Convert a line to begin with tabs when it starts with spaces."""

    stripped = line.lstrip()
    if not stripped or stripped.startswith("#"):
        return line, False
    if line.startswith("\t"):
        return line, False
    if not line.startswith(" "):
        return line, False

    leading_spaces = len(line) - len(line.lstrip(" "))
    tabs = leading_spaces // tab_size
    remainder = leading_spaces % tab_size
    if tabs == 0:
        tabs = 1
        remainder = 0

    new_line = "\t" * tabs + " " * remainder + stripped
    return new_line, new_line != line


def _apply_fixes(
    path: Path, lines: list[str], violations: Iterable[TabViolation], tab_size: int
) -> FixSummary | None:
    changed: list[int] = []
    for violation in violations:
        index = violation.line_number - 1
        original = lines[index]
        without_newline = original.rstrip("\r\n")
        newline = original[len(without_newline) :]
        fixed, mutated = _convert_line(without_newline, tab_size)
        if not mutated:
            continue
        lines[index] = f"{fixed}{newline}"
        changed.append(violation.line_number)
    if not changed:
        return None
    return FixSummary(path=path, lines=tuple(changed))


def fix_paths(paths: Sequence[Path], tab_size: int, check_only: bool) -> int:
    """Normalize indentation for each provided Makefile path."""

    exit_code = 0
    for path in paths:
        if not path.exists():
            message = json.dumps(
                {"path": path.as_posix(), "error": "file does not exist"}
            )
            raise FileNotFoundError(message)
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        violations = tuple(find_tab_violations(path))
        summary = _apply_fixes(path, lines, violations, tab_size)
        if summary is None:
            continue
        if check_only:
            exit_code = 1
        else:
            path.write_text("".join(lines), encoding="utf-8")
        sys.stdout.write(f"{summary.to_json()}\n")
    return exit_code


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=(Path("Makefile"),),
        help="Makefiles to normalize.",
    )
    parser.add_argument(
        "--tab-size",
        type=int,
        default=DEFAULT_TAB_SIZE,
        help="Number of spaces represented by a tab when rebuilding indentation.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run in dry-run mode; exit with status 1 if changes are required.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return fix_paths(tuple(args.paths), args.tab_size, args.check)


if __name__ == "__main__":
    raise SystemExit(main())
