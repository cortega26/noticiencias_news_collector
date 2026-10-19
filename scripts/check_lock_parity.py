#!/usr/bin/env python3
"""
check_lock_parity.py — fail when the venv does not match requirements.lock.

`requirements.lock` is the runtime truth (Dockerfile.serving installs only
that lock). `make bootstrap` then installs `requirements-security.lock`
into the same venv. Since plan 156 the security lock is constrained with
`-c requirements.lock`, so it is expected to agree with the runtime pins.
This gate compares every runtime pin with the version actually installed
in the running interpreter's environment and:

  - passes when every pin matches; the `KNOWN_BOOTSTRAP_OVERRIDES` map is
    empty and exists only as a fail-loud mechanism for a future deliberate
    collision;
  - fails on a mismatch, a missing package, or a stale exception (an entry
    whose collision no longer exists — delete it);
  - does not police packages that are not in `requirements.lock` (dev gate
    tools and the security lock's own dependencies).

The semgrep tool env split landed in plan 156; runtime/security divergence
is now a gate failure, not an enumerable exception.

Healing a red result: after a lock change run `make bootstrap` (delete the
`.venv/.bootstrap-complete` stamp first — bootstrap is stamp-gated) so the
installed environment catches up with the lock. If the failure is a new
collision rather than a stale venv, do not add an exception: report it.

Usage:
  scripts/check_lock_parity.py [--lock PATH]

Exit codes:
  0 — every runtime pin matches (known overrides included) and none is stale
  1 — a mismatch, a missing package, or a stale exception was found
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = REPO_ROOT / "requirements.lock"


# Empty since plan 156 (2026-10-19). The security lock now carries the same
# click/pyee/smmap pins as the runtime lock, and types-requests is not a
# runtime pin, so no deliberate divergence remains. The mechanism stays so a
# future collision fails loudly; never add an entry for a new mismatch.
@dataclass(frozen=True)
class KnownOverride:
    """A deliberate, documented divergence between lock and venv."""

    installed: str
    reason: str


KNOWN_BOOTSTRAP_OVERRIDES: Dict[str, KnownOverride] = {}

# `name==version`, optionally with extras: `psycopg[binary]==3.3.4`.
_PIN_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==(?P<version>[^\s\\]+)"
)


def canonical_name(name: str) -> str:
    """PEP 503 normalization, so lock and metadata names compare equal."""
    return re.sub(r"[-_.]+", "-", name).lower()


def load_lock(lock_path: Path) -> Dict[str, "LockPin"]:
    """Parse name==version pins from a hash-pinned requirements lock."""
    pins: Dict[str, LockPin] = {}
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        match = _PIN_RE.match(line.strip())
        if match is None:
            continue
        name = match.group("name")
        pins[canonical_name(name)] = LockPin(name=name, version=match.group("version"))
    if not pins:
        raise ValueError(f"{lock_path}: no 'name==version' pins found")
    return pins


def installed_version(name: str) -> Optional[str]:
    """Installed distribution version, or None when it is not installed."""
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


@dataclass(frozen=True)
class LockPin:
    """One runtime lock entry."""

    name: str
    version: str


@dataclass(frozen=True)
class Row:
    """One row of the comparison table."""

    name: str
    pinned: str
    installed: Optional[str]
    override: Optional[KnownOverride]
    stale: bool

    @property
    def ok(self) -> bool:
        if self.installed is None:
            return False
        expected = self.override.installed if self.override else self.pinned
        return self.installed == expected and not self.stale


def collect_rows(pins: Dict[str, LockPin]) -> List[Row]:
    """Compare every runtime pin against the running environment."""
    rows: List[Row] = []
    for key in sorted(pins):
        pin = pins[key]
        override = KNOWN_BOOTSTRAP_OVERRIDES.get(key)
        rows.append(
            Row(
                name=pin.name,
                pinned=pin.version,
                installed=installed_version(pin.name),
                override=override,
                stale=override is not None and override.installed == pin.version,
            )
        )
    return rows


def render_mismatches(rows: List[Row]) -> str:
    """Render only the failing rows, with the expected version."""
    headers = ("package", "lock pin", "installed", "expected", "problem")
    cells = []
    for row in rows:
        if row.ok:
            continue
        expected = row.override.installed if row.override else row.pinned
        if row.installed is None:
            problem = "missing from venv"
        elif row.stale:
            problem = "stale exception: collision resolved, delete the entry"
        else:
            problem = "version mismatch"
        cells.append(
            (row.name, row.pinned, row.installed or "<missing>", expected, problem)
        )

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
        "--lock",
        type=Path,
        default=DEFAULT_LOCK,
        help="runtime lock to compare against (default: requirements.lock)",
    )
    args = parser.parse_args(argv)

    try:
        pins = load_lock(args.lock)
    except (OSError, ValueError) as exc:
        print(f"[lock-parity] FAIL - cannot read lock: {exc}")
        return 1

    rows = collect_rows(pins)
    failures = [row for row in rows if not row.ok]
    overrides = [row for row in rows if row.override is not None]

    print(f"[lock-parity] runtime lock: {args.lock}")
    print(
        f"[lock-parity] checked {len(rows)} pins against the running "
        f"environment; {len(overrides)} known bootstrap override(s)"
    )
    if KNOWN_BOOTSTRAP_OVERRIDES:
        print(
            "[lock-parity] override keys: "
            + ", ".join(sorted(KNOWN_BOOTSTRAP_OVERRIDES))
        )

    if failures:
        print("\n[lock-parity] FAIL - the venv does not match the runtime lock:")
        print(render_mismatches(rows))
        print(
            "\n[lock-parity] heal: run `make bootstrap` after a lock change "
            "(remove .venv/.bootstrap-complete first — bootstrap is stamp-gated)."
        )
        return 1

    print("[lock-parity] OK - every runtime pin matches the installed environment")
    return 0


if __name__ == "__main__":
    sys.exit(main())
