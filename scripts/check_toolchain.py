#!/usr/bin/env python3
"""
check_toolchain.py — fail when the venv's gate tools drift from the pins.

`.pre-commit-config.yaml` is the single source of truth for what "clean"
means at commit time. This gate reads the pinned revisions of the hook
repos (ruff, black, isort, bandit), the `pdoc==X` pin in the local
`generate-api-docs` hook's `additional_dependencies`, and the explicit
`MYPY_PIN` constant below, then compares them with the versions installed
in the running interpreter's environment (the venv used by `make`).

Mypy has no pre-commit `rev`: its local hook runs `.venv/bin/python -m
mypy`, so the venv install *is* the pin. Raising `MYPY_PIN` is a deliberate
change: bump it here and in the Makefile's bootstrap install list together.

Healing a red result:
  - update the Makefile bootstrap install list to match the hook pins, then
    recreate the venv (`rm -rf .venv && make bootstrap`);
  - if a hook pin moved, prefer moving the venv to the hook (not the
    reverse); see plan 144's maintenance notes.

Usage:
  scripts/check_toolchain.py [--config PATH]

Exit codes:
  0 — every pinned tool is installed at the pinned version
  1 — a pin is missing/unreadable, or an installed version differs
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Dict, List, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"

# Mypy is a local (system) hook: no rev pins it, so the venv install is the
# pin. Raising it is deliberate — update this constant and the Makefile
# bootstrap line in the same change.
MYPY_PIN = "2.4.0"

# Hook repos whose `rev` pins a gate tool, keyed by lowercase URL.
HOOK_REPOS: Dict[str, str] = {
    "https://github.com/astral-sh/ruff-pre-commit": "ruff",
    "https://github.com/psf/black": "black",
    "https://github.com/pycqa/isort": "isort",
    "https://github.com/pycqa/bandit": "bandit",
}

PDOC_HOOK_ID = "generate-api-docs"


@dataclass(frozen=True)
class Pin:
    """A tool's pinned version plus where the pin came from."""

    version: str
    source: str


@dataclass(frozen=True)
class Row:
    """One row of the comparison table."""

    tool: str
    pin: Pin
    installed: Optional[str]

    @property
    def ok(self) -> bool:
        return self.installed == self.pin.version


def _as_list(value: object) -> List[object]:
    return value if isinstance(value, list) else []


def load_pins(config_path: Path) -> Dict[str, Pin]:
    """Read the gate-tool pins from the pre-commit configuration."""
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    repos = data.get("repos") if isinstance(data, dict) else None
    if not isinstance(repos, list):
        raise ValueError(f"{config_path}: no 'repos' list found")

    pins: Dict[str, Pin] = {}
    for repo in repos:
        if not isinstance(repo, dict):
            continue
        url = str(repo.get("repo", "")).lower().rstrip("/")
        tool = HOOK_REPOS.get(url)
        if tool is not None:
            rev = repo.get("rev")
            if not isinstance(rev, str) or not rev.strip():
                raise ValueError(f"{url}: missing 'rev' pin")
            pins[tool] = Pin(rev.strip().removeprefix("v"), url)

        for hook in _as_list(repo.get("hooks")):
            if not isinstance(hook, dict) or hook.get("id") != PDOC_HOOK_ID:
                continue
            for dependency in _as_list(hook.get("additional_dependencies")):
                text = str(dependency)
                if text.lower().startswith("pdoc=="):
                    version = text.split("==", 1)[1].strip()
                    pins["pdoc"] = Pin(
                        version, f"local hook '{PDOC_HOOK_ID}' dependencies"
                    )

    pins["mypy"] = Pin(MYPY_PIN, "scripts/check_toolchain.py MYPY_PIN")

    expected = set(HOOK_REPOS.values()) | {"pdoc", "mypy"}
    missing = sorted(expected - set(pins))
    if missing:
        raise ValueError(
            f"{config_path}: could not find pins for: {', '.join(missing)}"
        )
    return pins


def installed_version(module: str) -> Optional[str]:
    """Installed distribution version, or None when it is not installed."""
    try:
        return metadata.version(module)
    except metadata.PackageNotFoundError:
        return None


def collect_rows(pins: Dict[str, Pin]) -> List[Row]:
    """Build the comparison table, sorted by tool name."""
    return [
        Row(tool=tool, pin=pins[tool], installed=installed_version(tool))
        for tool in sorted(pins)
    ]


def render_table(rows: List[Row]) -> str:
    """Render the comparison table for humans and CI logs."""
    headers = ("tool", "pinned", "installed", "status", "pin source")
    cells = [
        (
            row.tool,
            row.pin.version,
            row.installed or "<missing>",
            "ok" if row.ok else "MISMATCH",
            row.pin.source,
        )
        for row in rows
    ]
    widths = [
        max(len(headers[index]), *(len(cell[index]) for cell in cells))
        for index in range(len(headers))
    ]
    lines = [
        "  ".join(value.ljust(widths[index]) for index, value in enumerate(headers)),
        "  ".join("-" * width for width in widths),
    ]
    lines.extend(
        "  ".join(value.ljust(widths[index]) for index, value in enumerate(cell))
        for cell in cells
    )
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="pre-commit configuration to read (default: repository root)",
    )
    args = parser.parse_args(argv)

    try:
        pins = load_pins(args.config)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"[toolchain] FAIL - cannot read pins: {exc}")
        return 1

    rows = collect_rows(pins)
    print(f"[toolchain] source of truth: {args.config}")
    print(render_table(rows))

    mismatches = [row.tool for row in rows if not row.ok]
    if mismatches:
        print(
            "\n[toolchain] FAIL - installed tools differ from the pinned "
            f"revisions: {', '.join(mismatches)}"
        )
        print(
            "[toolchain] heal: align the Makefile bootstrap install list with "
            "the pins, then `rm -rf .venv && make bootstrap`."
        )
        return 1

    print(f"\n[toolchain] OK - {len(rows)} gate tools match their pins")
    return 0


if __name__ == "__main__":
    sys.exit(main())
