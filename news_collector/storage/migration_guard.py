"""Read-only comparison between a database's applied Alembic revision and the
packaged migration head.

This module never creates, stamps, or upgrades a schema. It exists so that
application startup (or an operator) can *detect* a mismatch and fail loudly
— per plan 046's own rule, "application startup may verify revisions but
must never become the migration owner." Alembic (`scripts/migrate.py`) stays
the only thing that writes to `alembic_version` or DDL.

Deliberately builds its own bare engine via `build_database_url` instead of
going through `DatabaseManager` — that class's constructor calls
`Base.metadata.create_all` as a dev/test convenience, which would silently
create tables on a schema this guard is supposed to be checking untouched.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy import inspect as sqla_inspect
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from .database import build_database_url

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
ALEMBIC_DIR = REPO_ROOT / "alembic"


class RevisionState(str, enum.Enum):
    UP_TO_DATE = "up_to_date"
    BEHIND = "behind"
    AHEAD = "ahead"
    MISSING_VERSION_TABLE = "missing_version_table"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True)
class RevisionStatus:
    state: RevisionState
    current_revision: Optional[str]
    head_revision: Optional[str]
    detail: str

    @property
    def is_ready(self) -> bool:
        return self.state is RevisionState.UP_TO_DATE


def _script_directory() -> ScriptDirectory:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    return ScriptDirectory.from_config(cfg)


def build_readonly_engine(database_config: Dict[str, Any]) -> Engine:
    """Build a bare engine for revision checking only.

    No pooling tuning, no create_all, no SQLite pragmas — just enough to open
    a connection and read `alembic_version`.
    """
    url = build_database_url(database_config)
    return create_engine(url, pool_pre_ping=True)


def check_revision(engine: Engine) -> RevisionStatus:
    """Compare the database's `alembic_version` to the packaged head.

    Read-only: issues a single SELECT (or table-existence check) and never
    writes. Distinguishes four failure diagnostics plus the healthy case:

    - UP_TO_DATE: current revision equals packaged head.
    - BEHIND: current revision is an ancestor of head (needs `alembic upgrade head`).
    - AHEAD: current revision is not recognized as an ancestor of packaged head —
      either a newer deployment already migrated this database, or history
      has diverged. Never auto-resolved; always an operator decision.
    - MISSING_VERSION_TABLE: database has never been stamped by Alembic.
    - UNREACHABLE: connection or history itself is broken (e.g. multiple
      packaged heads, network/auth failure) — reported without leaking
      connection credentials.
    """
    script = _script_directory()
    heads = script.get_heads()
    if len(heads) != 1:
        return RevisionStatus(
            state=RevisionState.UNREACHABLE,
            current_revision=None,
            head_revision=None,
            detail=(
                f"Packaged migration history has {len(heads)} heads, "
                f"expected exactly 1: {heads}"
            ),
        )
    head = heads[0]

    try:
        with engine.connect() as conn:
            inspector = sqla_inspect(conn)
            if "alembic_version" not in inspector.get_table_names():
                return RevisionStatus(
                    state=RevisionState.MISSING_VERSION_TABLE,
                    current_revision=None,
                    head_revision=head,
                    detail=(
                        "Database has no alembic_version table; it has "
                        "never been stamped or migrated by Alembic."
                    ),
                )
            current = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
    except SQLAlchemyError as exc:
        return RevisionStatus(
            state=RevisionState.UNREACHABLE,
            current_revision=None,
            head_revision=head,
            detail=(
                f"Could not reach database to read alembic_version: "
                f"{type(exc).__name__}"
            ),
        )

    if current == head:
        return RevisionStatus(
            state=RevisionState.UP_TO_DATE,
            current_revision=current,
            head_revision=head,
            detail="Database revision matches packaged head.",
        )

    # Walk head's ancestor chain; if `current` is on it, the DB is simply behind.
    ancestors: set[str] = set()
    frontier = [head]
    while frontier:
        rev_id = frontier.pop()
        if rev_id in ancestors:
            continue
        ancestors.add(rev_id)
        revision = script.get_revision(rev_id)
        down = revision.down_revision
        if down is None:
            continue
        if isinstance(down, (tuple, list)):
            frontier.extend(down)
        else:
            frontier.append(down)

    if current in ancestors:
        return RevisionStatus(
            state=RevisionState.BEHIND,
            current_revision=current,
            head_revision=head,
            detail=f"Database is at {current!r}, behind packaged head {head!r}.",
        )

    return RevisionStatus(
        state=RevisionState.AHEAD,
        current_revision=current,
        head_revision=head,
        detail=(
            f"Database reports revision {current!r}, which this codebase's "
            f"migration history does not recognize as an ancestor of head "
            f"{head!r}. Either the database was migrated by newer code than "
            f"this deployment, or history has diverged — resolve manually, "
            f"do not auto-migrate."
        ),
    )
