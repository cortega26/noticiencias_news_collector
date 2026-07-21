#!/usr/bin/env python3
"""Read-only CLI: reports whether the configured database's Alembic revision
matches the packaged migration head.

Never mutates schema — this is a diagnostic, not a migration runner. Use
`scripts/migrate.py up` (or `alembic upgrade head`) to actually migrate.

Exit codes let an orchestrator fail a deploy/readiness check without this
script becoming the migration owner itself:
    0 = up to date
    2 = behind head
    3 = ahead of / diverged from packaged head
    4 = alembic_version table missing (never migrated)
    5 = unreachable (connection failure or broken packaged history)
"""

from __future__ import annotations

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from news_collector.config.settings import get_runtime_config  # noqa: E402
from news_collector.storage.migration_guard import (  # noqa: E402
    RevisionState,
    build_readonly_engine,
    check_revision,
)

_EXIT_CODES = {
    RevisionState.UP_TO_DATE: 0,
    RevisionState.BEHIND: 2,
    RevisionState.AHEAD: 3,
    RevisionState.MISSING_VERSION_TABLE: 4,
    RevisionState.UNREACHABLE: 5,
}


def main() -> int:
    database_config = get_runtime_config().database_config
    engine = build_readonly_engine(database_config)
    try:
        status = check_revision(engine)
    finally:
        engine.dispose()

    print(f"[migration-guard] state={status.state.value}")
    print(
        f"[migration-guard] current={status.current_revision} head={status.head_revision}"
    )
    print(f"[migration-guard] {status.detail}")
    return _EXIT_CODES[status.state]


if __name__ == "__main__":
    sys.exit(main())
