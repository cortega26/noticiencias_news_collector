"""Validate that Makefile recipes use tab indentation."""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


@dataclass(frozen=True)
class TabViolation:
    """Record of a Makefile line that is not tab-indented."""

    path: Path
    line_number: int
    line: str


def _iter_lines(path: Path) -> Iterable[tuple[int, str]]:
    content = path.read_text(encoding="utf-8").splitlines()
    for index, value in enumerate(content, start=1):
        yield index, value


def find_tab_violations(path: Path) -> list[TabViolation]:
    """Return all lines in ``path`` that start with spaces instead of tabs."""

    violations: list[TabViolation] = []
    for line_number, line in _iter_lines(path):
        stripped = line.lstrip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if line.startswith("\t"):
            continue
        if line.startswith(" "):
            violations.append(TabViolation(path=path, line_number=line_number, line=line))
    return violations


def _format_violation(violation: TabViolation) -> str:
    return (
        f"{{\"path\": \"{violation.path.as_posix()}\", "
        f"\"line\": {violation.line_number}, "
        f"\"content\": \"{violation.line.replace('\\', '\\\\').replace('\"', '\\\"')}\"}}"
    )


def validate_makefiles(paths: Sequence[Path]) -> int:
    """Validate each Makefile path and emit structured errors."""

    exit_code = 0
    for path in paths:
        if not path.exists():
            message = (
                f'{{"path": "{path.as_posix()}", '
                f'"error": "file does not exist"}}\n'
            )
            sys.stderr.write(message)
            return 1
        violations = find_tab_violations(path)
        if not violations:
            continue
        exit_code = 1
        for violation in violations:
            sys.stdout.write(f"{_format_violation(violation)}\n")
    return exit_code


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=(Path("Makefile"),),
        help="Makefile paths to validate.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return validate_makefiles(tuple(args.paths))


if __name__ == "__main__":
    raise SystemExit(main())
