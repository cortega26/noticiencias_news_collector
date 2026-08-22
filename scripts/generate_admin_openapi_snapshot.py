#!/usr/bin/env python3
"""
generate_admin_openapi_snapshot.py — deterministic OpenAPI document snapshot
for the admin/serving FastAPI app (plan 060, Phase 0).

Builds `create_app()` against an isolated, throwaway SQLite database (never
the production singleton), calls FastAPI's built-in `app.openapi()`, and
writes the resulting document to `.contract-snapshots/admin_openapi.snapshot.json`
with sorted keys for byte-identical, deterministic output across runs.

This is a baseline artifact for drift detection only — it is not wired into
any Makefile target or CI job in this phase (that wiring is Phase 1/6 work),
and it does not drive TypeScript client generation yet (that is Phase 6
work, per `plans/060/spec.md`, "Phase 6: Generate admin and publication
contracts").

Usage:
  PYTHONPATH=$(pwd) .venv/bin/python scripts/generate_admin_openapi_snapshot.py

(PYTHONPATH must include the repo root — mirrors the convention used by
other script invocations in this Makefile, e.g. `PYTHONPATH=$(CURDIR)` at
Makefile:216. Running the bare `python scripts/...py` form without it fails
with `ModuleNotFoundError: No module named 'news_collector'`, since Python
adds the script's own directory to `sys.path`, not the repo root.)
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from news_collector.serving import create_app
from news_collector.storage.database import DatabaseManager

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SNAPSHOT_PATH = _REPO_ROOT / ".contract-snapshots" / "admin_openapi.snapshot.json"


def generate_snapshot() -> Path:
    """Build the admin FastAPI app against an isolated database and write
    its OpenAPI document to `_SNAPSHOT_PATH`. Returns the written path."""
    db_path = Path(tempfile.mkdtemp()) / "openapi_snapshot.db"
    db_manager = DatabaseManager({"type": "sqlite", "path": db_path})
    app = create_app(database_manager=db_manager)

    document = app.openapi()

    _SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SNAPSHOT_PATH.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return _SNAPSHOT_PATH


def main() -> int:
    try:
        written_path = generate_snapshot()
    except Exception as exc:  # noqa: BLE001 - surface any failure, don't hide it
        print(
            f"generate_admin_openapi_snapshot: failed to generate snapshot: {exc}",
            file=sys.stderr,
        )
        return 1

    print(str(written_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
