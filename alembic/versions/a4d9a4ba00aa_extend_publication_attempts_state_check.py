"""extend_publication_attempts_state_check

Revision ID: a4d9a4ba00aa
Revises: effe4ec70d6d
Create Date: 2026-08-24 13:20:53.292058

Plan 060 / Phase 3c: widens ``ck_publication_attempts_state`` on
``publication_attempts`` to accept a fourth value, ``"PUBLISHING"``,
covering the pre-PR window ``mark_article_publishing``/
``PROrchestrator.attempt_recovery`` already track on ``article_metadata``
directly (see ``plans/060/phase-3c-dual-write/spec.md``). Purely a
CHECK-constraint change — no other column, index, or table touched.

SQLite has no ``ALTER TABLE ... DROP/ADD CONSTRAINT`` for CHECK
constraints, so this goes through batch mode (``render_as_batch=True``,
``alembic/env.py`` lines 83/109), which recreates the table under the
hood. This repo has no prior ``drop_constraint``/``create_check_constraint``
precedent to copy verbatim — checked every migration file under
``alembic/versions/`` (grepped for both calls); ``2447e261ecf4`` is only a
column-add batch example. This revision follows that file's *idempotency*
idiom (inspect current state, guard before acting) applied to a
constraint instead of a column.

Idempotent by design, same reason as ``effe4ec70d6d``: ``DatabaseManager``'s
``create_all`` already builds this constraint from the current
``models.py`` (already updated to the four-value tuple) before Alembic
ever runs against a fresh database, so ``upgrade()``/``downgrade()``
inspect the constraint's actual SQL text before acting rather than
assuming a particular starting state.

``downgrade()`` is data-preserving, not silently lossy: the three-value
constraint being restored cannot represent ``"PUBLISHING"``, so
``downgrade()`` raises ``NotImplementedError`` if any row is currently in
that state, rather than deleting or reinterpreting it — this program's
additive-only / no-data-loss rule. No prior migration in this repo has
this exact irreversibility pattern to mirror: ``effe4ec70d6d``'s own
``downgrade()`` is fully reversible (it only ever added five brand-new
tables, so dropping them loses nothing that existed before it ran) —
checked that file directly, confirmed no data-loss guard exists there to
copy. This revision is the first one in this repo where downgrade can
lose representable data, hence the new guard.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "a4d9a4ba00aa"
down_revision: Union[str, Sequence[str], None] = "effe4ec70d6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors news_collector/storage/models.py exactly — keep both in sync.
# (Public name, not underscore-prefixed, on purpose: matches the convention
# effe4ec70d6d set for its own hand-copied vocabulary constants, and lets
# tests/test_database_migrations.py's vocabulary-parity test import this
# module and compare it against models.PUBLICATION_ATTEMPT_STATE_VALUES by
# name.)
PUBLICATION_ATTEMPT_STATE_VALUES = ("PUBLISHING", "PR_CREATED", "REJECTED", "COMPLETED")
_OLD_STATE_VALUES = ("PR_CREATED", "REJECTED", "COMPLETED")
_CONSTRAINT_NAME = "ck_publication_attempts_state"


def _check(values: tuple) -> str:
    return "state IN ({})".format(", ".join(f"'{v}'" for v in values))


def _current_constraint_sql(inspector) -> Union[str, None]:
    """SQL text of ck_publication_attempts_state as it exists right now, or
    None if the constraint (or the table) isn't there at all."""
    for constraint in inspector.get_check_constraints("publication_attempts"):
        if constraint["name"] == _CONSTRAINT_NAME:
            return constraint["sqltext"]
    return None


def upgrade() -> None:
    """Widen ck_publication_attempts_state to accept "PUBLISHING"."""
    bind = op.get_bind()
    inspector = inspect(bind)

    current_sql = _current_constraint_sql(inspector)
    if current_sql is not None and "PUBLISHING" in current_sql:
        # Already widened — e.g. create_all built the table from the
        # current (already four-value) models.py on a fresh database.
        return

    with op.batch_alter_table("publication_attempts", schema=None) as batch_op:
        batch_op.drop_constraint(_CONSTRAINT_NAME, type_="check")
        batch_op.create_check_constraint(
            _CONSTRAINT_NAME, _check(PUBLICATION_ATTEMPT_STATE_VALUES)
        )


def downgrade() -> None:
    """Restore the three-value constraint.

    Additive-only / no-data-loss: refuses to run if any row is in the
    "PUBLISHING" state the three-value constraint cannot represent,
    rather than deleting or reinterpreting it.
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    current_sql = _current_constraint_sql(inspector)
    if current_sql is not None and "PUBLISHING" not in current_sql:
        # Already narrowed.
        return

    publishing_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM publication_attempts WHERE state = 'PUBLISHING'")
    ).scalar_one()
    if publishing_count:
        raise NotImplementedError(
            f"Cannot downgrade past a4d9a4ba00aa: {publishing_count} "
            "publication_attempts row(s) are in the 'PUBLISHING' state, which "
            "the three-value ck_publication_attempts_state constraint being "
            "restored cannot represent. This program is additive-only / "
            "no-data-loss (see plans/060/phase-3c-dual-write/spec.md); "
            "resolve those rows to a representable state before downgrading."
        )

    with op.batch_alter_table("publication_attempts", schema=None) as batch_op:
        batch_op.drop_constraint(_CONSTRAINT_NAME, type_="check")
        batch_op.create_check_constraint(_CONSTRAINT_NAME, _check(_OLD_STATE_VALUES))
