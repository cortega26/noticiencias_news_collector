#!/usr/bin/env python3
"""Deterministic admin OpenAPI export and drift check (plan 080 Phase 2; the
first bounded slice of plan 060 Phase 6).

Builds the serving/admin FastAPI app against an isolated, throwaway SQLite
database, calls FastAPI's built-in ``app.openapi()`` without entering the
lifespan (no recovery, no dispatch, no server, no requests), and either writes
the document to a committed artifact or verifies that the committed artifact
matches a fresh export byte for byte.

This supersedes ``scripts/generate_admin_openapi_snapshot.py`` and
``.contract-snapshots/admin_openapi.snapshot.json`` (plan 060 Phase 0): the
single canonical artifact now lives next to its consumer at
``apps/admin/openapi.json`` so the admin build works offline from committed
files.

Usage:
  PYTHONPATH=$(pwd) .venv/bin/python scripts/export_admin_openapi.py --output apps/admin/openapi.json
  PYTHONPATH=$(pwd) .venv/bin/python scripts/export_admin_openapi.py --check apps/admin/openapi.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Must run before any news_collector import: keeps module-level initialisation
# (logger, metrics, config singletons) inside the established isolation
# convention. Local to this schema-only process.
os.environ.setdefault("NEWS_COLLECTOR_TEST_MODE", "1")
# Importing the serving package opens the enrichment-metrics singleton, whose
# path derives from RUN_ENVIRONMENT. Force the isolated test environment so a
# schema export on a production host can never touch data/metrics/production/.
os.environ["RUN_ENVIRONMENT"] = "test"

from news_collector.serving import create_app  # noqa: E402
from news_collector.storage.database import DatabaseManager  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUTPUT = _REPO_ROOT / "apps" / "admin" / "openapi.json"


def render_document() -> bytes:
    """Return the deterministic UTF-8 bytes of the app's OpenAPI document.

    The temporary database and manager are always released: production state
    (default manager, caches, logs) is never touched.
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="admin-openapi-"))
    manager: DatabaseManager | None = None
    try:
        manager = DatabaseManager({"type": "sqlite", "path": temp_dir / "openapi.db"})
        app = create_app(database_manager=manager)
        document = app.openapi()
        return (
            json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode("utf-8")
    finally:
        if manager is not None:
            manager.close()
        shutil.rmtree(temp_dir, ignore_errors=True)


def _mismatch_context(fresh: bytes, existing: bytes) -> str:
    """First differing line plus byte counts, for an actionable failure."""
    fresh_lines = fresh.decode("utf-8", errors="replace").splitlines()
    existing_lines = existing.decode("utf-8", errors="replace").splitlines()
    for index, (fresh_line, existing_line) in enumerate(
        zip(fresh_lines, existing_lines), start=1
    ):
        if fresh_line != existing_line:
            return (
                f"first difference at line {index}:\n"
                f"  fresh:    {fresh_line.strip()[:160]}\n"
                f"  existing: {existing_line.strip()[:160]}"
            )
    return (
        f"line counts differ (fresh {len(fresh_lines)}, existing {len(existing_lines)})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export or check the admin OpenAPI artifact."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--output",
        type=Path,
        metavar="PATH",
        nargs="?",
        const=_DEFAULT_OUTPUT,
        help=f"write the schema artifact (default: {_DEFAULT_OUTPUT.relative_to(_REPO_ROOT)})",
    )
    group.add_argument(
        "--check",
        type=Path,
        metavar="PATH",
        help="verify PATH matches a fresh export; never rewrites it",
    )
    args = parser.parse_args(argv)

    try:
        fresh = render_document()
    except Exception as exc:  # noqa: BLE001 - surface any failure, don't hide it
        print(f"export_admin_openapi: generation failed: {exc}", file=sys.stderr)
        return 1

    if args.output is not None:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(fresh)
        print(str(target))
        return 0

    target = Path(args.check)
    if not target.exists():
        print(
            f"export_admin_openapi: missing artifact {target}; "
            "run `make admin-contracts-generate`",
            file=sys.stderr,
        )
        return 1

    existing = target.read_bytes()
    if existing != fresh:
        print(
            f"export_admin_openapi: stale artifact {target}\n"
            f"{_mismatch_context(fresh, existing)}",
            file=sys.stderr,
        )
        return 1

    print(f"export_admin_openapi: {target} is up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
