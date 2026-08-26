"""Tests for automatic schema migrations applied by DatabaseManager."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import inspect as sqla_inspect
from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parents[1]

from unittest.mock import patch

from news_collector import config as app_config
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import (
    WORKFLOW_RUN_ACTIVE_STATUS,
    WorkflowRun,
    WorkflowStageAttempt,
)

# The five Phase 3a lineage tables (Plan 060) — used by the schema-parity
# and constraint tests below.
NEW_LIFECYCLE_TABLES = [
    "workflow_runs",
    "workflow_stage_attempts",
    "editorial_decisions",
    "publication_attempts",
    "publication_events",
]


def _create_legacy_sources_table(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                CREATE TABLE sources (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    credibility_score REAL NOT NULL,
                    category TEXT NOT NULL,
                    update_frequency TEXT,
                    last_checked TIMESTAMP,
                    last_successful_check TIMESTAMP,
                    last_article_found TIMESTAMP,
                    total_articles_collected INTEGER DEFAULT 0,
                    articles_this_month INTEGER DEFAULT 0,
                    average_articles_per_check REAL DEFAULT 0.0,
                    success_rate REAL DEFAULT 1.0,
                    duplicate_rate REAL DEFAULT 0.0,
                    average_article_score REAL,
                    is_active INTEGER DEFAULT 1,
                    consecutive_failures INTEGER DEFAULT 0,
                    error_message TEXT,
                    custom_config TEXT
                );
                """)
            conn.commit()
        finally:
            cursor.close()
    finally:
        conn.close()


@pytest.mark.parametrize(
    "missing_columns",
    [
        {
            "suppressed_until",
            "suppression_reason",
            "auto_suppressed",
            "dq_consecutive_anomalies",
            "last_canary_check",
            "last_canary_status",
        }
    ],
)
def test_database_manager_backfills_suppression_columns(
    tmp_path: Path, missing_columns: set[str]
) -> None:
    """The manager should auto-upgrade legacy source tables missing suppression fields."""

    db_path = tmp_path / "legacy.db"
    _create_legacy_sources_table(db_path)

    manager = DatabaseManager(database_config={"type": "sqlite", "path": db_path})
    try:
        # 1. Verify that DatabaseManager properly refuses to touch the schema
        with manager.engine.connect() as connection:
            inspector = sqla_inspect(connection)
            columns = {col["name"] for col in inspector.get_columns("sources")}

        # Check a sample column is MISSING initially
        assert (
            "auto_suppressed" not in columns
        ), "DatabaseManager should not auto-migrate anymore"

        # 2. Run Alembic Migration Programmatically
        from alembic import command
        from alembic.config import Config

        # Setup Alembic Config (point to alembic.ini in root)
        alembic_cfg = Config(str(ROOT / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
        # We must also patch the app config because env.py reads from it
        test_db_config = {"type": "sqlite", "path": str(db_path)}

        with patch.dict(app_config.DATABASE_CONFIG, test_db_config, clear=True):
            # Stamp it as valid legacy state first (optional but good for robustness)
            command.stamp(alembic_cfg, "cb486d1d980d")  # Stamp as initial revision

            # Now run the smart migration
            command.upgrade(alembic_cfg, "head")

        # 3. Verify columns exist after migration
        with manager.engine.connect() as connection:
            inspector = sqla_inspect(connection)
            columns = {col["name"] for col in inspector.get_columns("sources")}

        for column in missing_columns:
            assert (
                column in columns
            ), f"Expected column '{column}' to be created via migration"
    finally:
        manager.close()


def test_database_manager_has_article_publication_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "articles.db"

    manager = DatabaseManager(database_config={"type": "sqlite", "path": db_path})
    try:
        with manager.engine.connect() as connection:
            inspector = sqla_inspect(connection)
            columns = {col["name"] for col in inspector.get_columns("articles")}

        assert "published_at" in columns
        assert "published_url" in columns
    finally:
        manager.close()


def test_database_manager_creates_content_hash_unique_index(tmp_path: Path) -> None:
    db_path = tmp_path / "articles_index.db"

    manager = DatabaseManager(database_config={"type": "sqlite", "path": db_path})
    try:
        with manager.engine.connect() as connection:
            inspector = sqla_inspect(connection)
            indexes = {idx["name"] for idx in inspector.get_indexes("articles")}

        assert "uq_articles_content_hash" in indexes
    finally:
        manager.close()


def test_database_manager_creates_score_logs_latest_index(tmp_path: Path) -> None:
    db_path = tmp_path / "score_logs_index.db"

    manager = DatabaseManager(database_config={"type": "sqlite", "path": db_path})
    try:
        with manager.engine.connect() as connection:
            inspector = sqla_inspect(connection)
            indexes = {idx["name"] for idx in inspector.get_indexes("score_logs")}

        assert "idx_score_logs_article_latest" in indexes
    finally:
        manager.close()


def test_empty_database_upgrades_to_head(tmp_path: Path) -> None:
    """A fresh database created by SQLAlchemy must reach Alembic head."""
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "empty_to_head.db"
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    test_db_config: dict = {"type": "sqlite", "path": db_path}

    with patch.dict(app_config.DATABASE_CONFIG, test_db_config, clear=True):
        mgr = DatabaseManager(database_config=test_db_config)
        mgr.close()
        command.stamp(alembic_cfg, "cb486d1d980d")
        command.upgrade(alembic_cfg, "head")

    mgr = DatabaseManager(database_config={"type": "sqlite", "path": db_path})
    try:
        with mgr.engine.connect() as connection:
            inspector = sqla_inspect(connection)
            tables = inspector.get_table_names()
        assert "articles" in tables
        assert "sources" in tables
        assert "score_logs" in tables
    finally:
        mgr.close()


def test_alembic_single_head() -> None:
    """The migration history must have exactly one linear head."""
    from alembic import script
    from alembic.config import Config

    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    directory = script.ScriptDirectory.from_config(alembic_cfg)

    heads = directory.get_heads()
    assert len(heads) == 1, f"Expected 1 head, got {len(heads)}: {heads}"


def test_alembic_upgrade_head_is_idempotent(tmp_path: Path) -> None:
    """Running upgrade to head twice must succeed without error."""
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "idempotent.db"
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    test_db_config: dict = {"type": "sqlite", "path": db_path}

    with patch.dict(app_config.DATABASE_CONFIG, test_db_config, clear=True):
        mgr = DatabaseManager(database_config=test_db_config)
        mgr.close()
        command.stamp(alembic_cfg, "cb486d1d980d")
        command.upgrade(alembic_cfg, "head")
        # Second upgrade must be a no-op
        command.upgrade(alembic_cfg, "head")

    # Verify the DB is usable
    mgr = DatabaseManager(database_config={"type": "sqlite", "path": db_path})
    try:
        with mgr.engine.connect() as connection:
            inspector = sqla_inspect(connection)
            assert "articles" in inspector.get_table_names()
    finally:
        mgr.close()


ALL_REVISIONS = [
    "cb486d1d980d",  # initial_schema
    "2447e261ecf4",  # consolidate_refinery_schema
    "a3f1b2c4d5e6",  # add_content_mode_to_articles
    "a54ba7f7dabb",  # add_blacklist_columns
    "b61c2d3e4f50",  # add_score_logs_latest_index
    "effe4ec70d6d",  # add_durable_lifecycle_tables
    "a4d9a4ba00aa",  # extend_publication_attempts_state_check
    "84cf98a379c1",  # extend_workflow_runs_durable_dispatch (head)
]

# 2447e261ecf4's downgrade() is intentionally incomplete (its own comment says
# "omitting exhaustive list for brevity") — it drops 2 of the ~10 columns
# upgrade() adds and doesn't touch the articles-table additions or indexes at
# all. It is not a "declared supported" downgrade per this plan's Step 2, so
# it is excluded from the roundtrip test below rather than silently trusted.
REVISIONS_WITH_SUPPORTED_DOWNGRADE = [
    "a3f1b2c4d5e6",
    "a54ba7f7dabb",
    "b61c2d3e4f50",
    "effe4ec70d6d",
    "a4d9a4ba00aa",
    "84cf98a379c1",
]


@pytest.mark.parametrize("revision", ALL_REVISIONS)
def test_every_legacy_revision_reaches_head(tmp_path: Path, revision: str) -> None:
    """Every supported starting state must reach head via `alembic upgrade head`."""
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / f"from_{revision}.db"
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    test_db_config = {"type": "sqlite", "path": db_path}

    with patch.dict(app_config.DATABASE_CONFIG, test_db_config, clear=True):
        # DatabaseManager's create_all builds every table this codebase's
        # current models declare, mirroring how any real deployment reaches
        # this state — Alembic revisions are additive catch-up scripts for
        # columns already present on the models create_all uses, and every
        # upgrade() body is idempotent (checks the column doesn't already
        # exist before adding it). This test proves each stamped starting
        # revision reaches head without error, not that the raw pre-model
        # SQL from years ago still exists somewhere.
        mgr = DatabaseManager(database_config=test_db_config)
        mgr.close()
        command.stamp(alembic_cfg, revision)
        command.upgrade(alembic_cfg, "head")

        from alembic import script as alembic_script

        directory = alembic_script.ScriptDirectory.from_config(alembic_cfg)
        head = directory.get_heads()[0]

        conn = sqlite3.connect(db_path)
        try:
            current = conn.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0]
        finally:
            conn.close()
    assert current == head


@pytest.mark.parametrize("revision", REVISIONS_WITH_SUPPORTED_DOWNGRADE)
def test_downgrade_upgrade_roundtrip(tmp_path: Path, revision: str) -> None:
    """Downgrading one revision and re-upgrading must return to head cleanly."""
    from alembic import command
    from alembic import script as alembic_script
    from alembic.config import Config

    db_path = tmp_path / f"roundtrip_{revision}.db"
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    test_db_config: dict = {"type": "sqlite", "path": db_path}

    with patch.dict(app_config.DATABASE_CONFIG, test_db_config, clear=True):
        mgr = DatabaseManager(database_config=test_db_config)
        mgr.close()
        command.stamp(alembic_cfg, "head")

        directory = alembic_script.ScriptDirectory.from_config(alembic_cfg)
        revision_obj = directory.get_revision(revision)
        down_target = revision_obj.down_revision
        assert isinstance(down_target, str), (
            f"{revision} has a non-linear down_revision; roundtrip test "
            "assumes a single linear predecessor"
        )

        command.downgrade(alembic_cfg, down_target)
        command.upgrade(alembic_cfg, "head")

        head = directory.get_heads()[0]
        conn = sqlite3.connect(db_path)
        try:
            current = conn.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0]
        finally:
            conn.close()
    assert current == head


def test_model_metadata_matches_alembic_head_schema(tmp_path: Path) -> None:
    """Every column SQLAlchemy models declare must exist after `upgrade head`.

    This is the drift check: deleting a migration op or adding an
    un-migrated model column must fail this test.
    """
    from alembic import command
    from alembic.config import Config

    from news_collector.storage.models import Base

    db_path = tmp_path / "metadata_parity.db"
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    test_db_config: dict = {"type": "sqlite", "path": db_path}

    with patch.dict(app_config.DATABASE_CONFIG, test_db_config, clear=True):
        # Every migration here assumes create_all already created the base
        # tables (Alembic revisions only ALTER/ADD, never CREATE TABLE — see
        # cb486d1d980d, which retypes columns on a "sources" table it never
        # creates). Bootstrap through DatabaseManager first, as production
        # startup does, before applying Alembic on top.
        mgr = DatabaseManager(database_config=test_db_config)
        mgr.close()
        command.upgrade(alembic_cfg, "head")

    mgr = DatabaseManager(database_config={"type": "sqlite", "path": db_path})
    try:
        with mgr.engine.connect() as connection:
            inspector = sqla_inspect(connection)
            for table in Base.metadata.sorted_tables:
                actual_columns = {
                    col["name"] for col in inspector.get_columns(table.name)
                }
                expected_columns = {col.name for col in table.columns}
                missing = expected_columns - actual_columns
                assert not missing, (
                    f"Table '{table.name}' is missing columns declared on "
                    f"the model but never added by an Alembic revision: "
                    f"{missing}"
                )
    finally:
        mgr.close()


def test_alembic_history_is_fully_linear() -> None:
    """Every revision except the base has exactly one down_revision (no branches)."""
    from alembic import script
    from alembic.config import Config

    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    directory = script.ScriptDirectory.from_config(alembic_cfg)

    revisions = list(directory.walk_revisions())
    assert len(revisions) == len(ALL_REVISIONS)
    for rev in revisions:
        if rev.down_revision is not None:
            assert isinstance(rev.down_revision, str), (
                f"{rev.revision} has a branched/merge down_revision: "
                f"{rev.down_revision}"
            )


def test_alembic_revision_guard_detects_behind(tmp_path: Path) -> None:
    """A database behind head must be detected without mutating schema."""
    from alembic import command
    from alembic import script as alembic_script
    from alembic.config import Config

    db_path = tmp_path / "behind.db"
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    test_db_config: dict = {"type": "sqlite", "path": db_path}

    with patch.dict(app_config.DATABASE_CONFIG, test_db_config, clear=True):
        mgr = DatabaseManager(database_config=test_db_config)
        mgr.close()
        # Stamp as one revision behind head
        command.stamp(alembic_cfg, "b61c2d3e4f50")

    # Read-only check: alembic_version != head. Head is fetched dynamically
    # (not hardcoded) so this test doesn't go stale every time a new
    # revision lands on top — it only cares that "behind" is detectable.
    directory = alembic_script.ScriptDirectory.from_config(alembic_cfg)
    head = directory.get_heads()[0]

    from news_collector.storage.database import DatabaseManager as DM

    db_mgr = DM(database_config={"type": "sqlite", "path": db_path})
    try:
        with db_mgr.engine.connect() as conn:
            result = conn.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar()
        assert result == "b61c2d3e4f50"
        assert result != head
    finally:
        db_mgr.close()


def test_migration_vocabulary_constants_match_models() -> None:
    """effe4ec70d6d duplicates its CHECK-constraint vocabularies by hand
    from news_collector/storage/models.py (Alembic revisions can't import
    application models — they must keep working after models.py evolves).
    This is the only thing that would catch one side being edited without
    the other; test_new_lifecycle_tables_schema_parity only compares
    constraint *names*, not the allowed values each constraint enforces.

    PUBLICATION_ATTEMPT_STATE_VALUES is intentionally excluded from this
    comparison: effe4ec70d6d's copy is a frozen historical snapshot of
    what the constraint looked like when that revision was written
    (three values). a4d9a4ba00aa (Plan 060 / Phase 3c) is the migration
    that now owns keeping this particular vocabulary in sync with
    models.py (four values) — checked separately below by
    test_publication_attempt_state_values_match_latest_migration.

    WORKFLOW_RUN_STATUS_VALUES is excluded for the same reason:
    effe4ec70d6d's copy is frozen at its original four values
    ("running", "completed", "failed", "cancelled"); 84cf98a379c1
    (Plan 060 / Phase 4a) is the migration that now owns this vocabulary
    (six values, "completed" renamed to "succeeded") — checked separately
    below by test_workflow_run_status_values_match_latest_migration.
    WORKFLOW_RUN_ACTIVE_STATUS is unchanged ("running") and stays in the
    comparison below.
    """
    import importlib.util

    from news_collector.storage import models

    module_path = (
        ROOT / "alembic" / "versions" / "effe4ec70d6d_add_durable_lifecycle_tables.py"
    )
    spec = importlib.util.spec_from_file_location("effe4ec70d6d_migration", module_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    pairs = [
        ("WORKFLOW_RUN_ACTIVE_STATUS",),
        ("WORKFLOW_STAGE_ATTEMPT_STATUS_VALUES",),
        ("EDITORIAL_DECISION_TYPE_VALUES",),
        ("EDITORIAL_DECISION_OUTCOME_VALUES",),
        ("PUBLICATION_EVENT_TYPE_VALUES",),
    ]
    for (name,) in pairs:
        assert getattr(models, name) == getattr(
            migration, name
        ), f"{name} diverged between models.py and the migration"


def test_publication_attempt_state_values_match_latest_migration() -> None:
    """a4d9a4ba00aa is the latest migration to touch
    ck_publication_attempts_state — its own hand-copied
    PUBLICATION_ATTEMPT_STATE_VALUES must match models.py exactly, the same
    "can't import application models" reasoning as
    test_migration_vocabulary_constants_match_models above.
    """
    import importlib.util

    from news_collector.storage import models

    module_path = (
        ROOT
        / "alembic"
        / "versions"
        / "a4d9a4ba00aa_extend_publication_attempts_state_check.py"
    )
    spec = importlib.util.spec_from_file_location("a4d9a4ba00aa_migration", module_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert models.PUBLICATION_ATTEMPT_STATE_VALUES == (
        migration.PUBLICATION_ATTEMPT_STATE_VALUES
    ), "PUBLICATION_ATTEMPT_STATE_VALUES diverged between models.py and a4d9a4ba00aa"


def test_workflow_run_status_values_match_latest_migration() -> None:
    """84cf98a379c1 (Plan 060 / Phase 4a) is the latest migration to touch
    ck_workflow_runs_status — its own hand-copied WORKFLOW_RUN_STATUS_VALUES
    and WORKFLOW_RUN_QUEUEABLE_STATUSES must match models.py exactly, same
    "can't import application models" reasoning as
    test_publication_attempt_state_values_match_latest_migration above.
    """
    import importlib.util

    from news_collector.storage import models

    module_path = (
        ROOT
        / "alembic"
        / "versions"
        / "84cf98a379c1_extend_workflow_runs_durable_dispatch.py"
    )
    spec = importlib.util.spec_from_file_location("84cf98a379c1_migration", module_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert (
        models.WORKFLOW_RUN_STATUS_VALUES == migration.WORKFLOW_RUN_STATUS_VALUES
    ), "WORKFLOW_RUN_STATUS_VALUES diverged between models.py and 84cf98a379c1"
    assert (
        models.WORKFLOW_RUN_QUEUEABLE_STATUSES
        == migration.WORKFLOW_RUN_QUEUEABLE_STATUSES
    ), "WORKFLOW_RUN_QUEUEABLE_STATUSES diverged between models.py and 84cf98a379c1"


def test_lifecycle_tables_upgrade_body_is_reentrant_within_one_connection() -> None:
    """effe4ec70d6d's upgrade() must be safe to call twice in a row against
    the same connection without raising "already exists" — this is the
    actual idempotency guarantee the create_table/create_index guards are
    for (DatabaseManager's create_all may have already built these tables
    before Alembic runs). Exercises upgrade() directly via a raw
    Operations context rather than through `alembic upgrade head` twice,
    to prove the guard logic itself, not just that Alembic's version-guard
    short-circuits a same-revision re-run.
    """
    import importlib.util

    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine

    module_path = (
        ROOT / "alembic" / "versions" / "effe4ec70d6d_add_durable_lifecycle_tables.py"
    )
    spec = importlib.util.spec_from_file_location("effe4ec70d6d_migration", module_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                migration.upgrade()
                migration.upgrade()  # must not raise

            inspector = sqla_inspect(conn)
            for table in NEW_LIFECYCLE_TABLES:
                assert table in inspector.get_table_names()
    finally:
        engine.dispose()


def _table_schema_snapshot(inspector, table_name: str) -> dict:
    """Column/index/constraint/FK shape for one table, order-independent."""
    return {
        "columns": {col["name"] for col in inspector.get_columns(table_name)},
        "indexes": {idx["name"] for idx in inspector.get_indexes(table_name)},
        "check_constraints": {
            c["name"] for c in inspector.get_check_constraints(table_name)
        },
        "unique_constraints": {
            (uq["name"], tuple(uq["column_names"]))
            for uq in inspector.get_unique_constraints(table_name)
        },
        "foreign_keys": {
            (
                tuple(fk["constrained_columns"]),
                fk["referred_table"],
                tuple(sorted((fk.get("options") or {}).items())),
            )
            for fk in inspector.get_foreign_keys(table_name)
        },
    }


def test_new_lifecycle_tables_schema_parity(tmp_path: Path) -> None:
    """A fresh create_all DB and a legacy-stamp-then-upgrade-head DB must
    produce byte-identical schema for the five Phase 3a lineage tables:
    same columns, same index names, same check-constraint names, same
    unique constraints, same FK targets/ondelete. This is what keeps
    news_collector/storage/models.py and the effe4ec70d6d migration from
    silently drifting apart (Step 1's rationale for adding the models at
    all, not just the migration).
    """
    from alembic import command
    from alembic.config import Config

    # DB A: fresh create_all only, no Alembic involved.
    fresh_db_path = tmp_path / "fresh_create_all.db"
    fresh_mgr = DatabaseManager(
        database_config={"type": "sqlite", "path": fresh_db_path}
    )
    fresh_mgr.close()

    # DB B: legacy stamp, then `alembic upgrade head` (mirrors
    # test_every_legacy_revision_reaches_head's own bootstrap pattern).
    migrated_db_path = tmp_path / "migrated_to_head.db"
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    test_db_config = {"type": "sqlite", "path": migrated_db_path}
    with patch.dict(app_config.DATABASE_CONFIG, test_db_config, clear=True):
        migrated_mgr = DatabaseManager(database_config=test_db_config)
        migrated_mgr.close()
        command.stamp(alembic_cfg, "cb486d1d980d")
        command.upgrade(alembic_cfg, "head")

    from sqlalchemy import create_engine

    fresh_engine = create_engine(f"sqlite:///{fresh_db_path}")
    migrated_engine = create_engine(f"sqlite:///{migrated_db_path}")
    try:
        fresh_inspector = sqla_inspect(fresh_engine)
        migrated_inspector = sqla_inspect(migrated_engine)
        for table in NEW_LIFECYCLE_TABLES:
            fresh_snapshot = _table_schema_snapshot(fresh_inspector, table)
            migrated_snapshot = _table_schema_snapshot(migrated_inspector, table)
            assert fresh_snapshot == migrated_snapshot, (
                f"Schema drift on '{table}' between create_all and "
                f"alembic upgrade head: {fresh_snapshot} != {migrated_snapshot}"
            )
    finally:
        fresh_engine.dispose()
        migrated_engine.dispose()


def test_workflow_runs_one_active_collection_partial_unique_index_raises(
    tmp_path: Path,
) -> None:
    """The partial unique index actually constrains, not just exists."""
    db_path = tmp_path / "one_active_collection.db"
    mgr = DatabaseManager(database_config={"type": "sqlite", "path": db_path})
    try:
        now = datetime.now(timezone.utc)
        with mgr.SessionLocal() as session:
            session.add(
                WorkflowRun(
                    run_type="collection",
                    status=WORKFLOW_RUN_ACTIVE_STATUS,
                    started_at=now,
                )
            )
            session.commit()

            session.add(
                WorkflowRun(
                    run_type="collection",
                    status=WORKFLOW_RUN_ACTIVE_STATUS,
                    started_at=now,
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        mgr.close()


def test_workflow_runs_one_active_collection_blocks_queued_against_running(
    tmp_path: Path,
) -> None:
    """Plan 060 / Phase 4a widened the partial index's predicate from
    ``status = 'running'`` to ``status IN ('queued', 'running')`` — a
    queued-but-not-yet-started duplicate collection request must also
    conflict, not just two 'running' rows."""
    db_path = tmp_path / "queued_vs_running.db"
    mgr = DatabaseManager(database_config={"type": "sqlite", "path": db_path})
    try:
        now = datetime.now(timezone.utc)
        with mgr.SessionLocal() as session:
            session.add(
                WorkflowRun(run_type="collection", status="running", started_at=now)
            )
            session.commit()

            session.add(
                WorkflowRun(run_type="collection", status="queued", started_at=now)
            )
            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        mgr.close()


def test_workflow_runs_idempotency_key_active_partial_unique_index_raises(
    tmp_path: Path,
) -> None:
    """A second queued/running row with the same (run_type, idempotency_key)
    must conflict; a terminal row's key must be reusable."""
    db_path = tmp_path / "idempotency_key.db"
    mgr = DatabaseManager(database_config={"type": "sqlite", "path": db_path})
    try:
        now = datetime.now(timezone.utc)
        with mgr.SessionLocal() as session:
            session.add(
                WorkflowRun(
                    run_type="refinery",
                    status="running",
                    started_at=now,
                    idempotency_key="key-1",
                )
            )
            session.commit()

            session.add(
                WorkflowRun(
                    run_type="refinery",
                    status="queued",
                    started_at=now,
                    idempotency_key="key-1",
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        mgr.close()


def test_workflow_runs_idempotency_key_reusable_after_terminal(
    tmp_path: Path,
) -> None:
    """Once the first row reaches a terminal status, the same
    (run_type, idempotency_key) pair may be reused by a new row — the
    partial index only scopes queued/running rows."""
    db_path = tmp_path / "idempotency_key_reuse.db"
    mgr = DatabaseManager(database_config={"type": "sqlite", "path": db_path})
    try:
        now = datetime.now(timezone.utc)
        with mgr.SessionLocal() as session:
            session.add(
                WorkflowRun(
                    run_type="refinery",
                    status="succeeded",
                    started_at=now,
                    idempotency_key="key-2",
                )
            )
            session.commit()

            session.add(
                WorkflowRun(
                    run_type="refinery",
                    status="queued",
                    started_at=now,
                    idempotency_key="key-2",
                )
            )
            session.commit()  # must not raise
    finally:
        mgr.close()


def test_workflow_runs_downgrade_refuses_with_unrepresentable_status(
    tmp_path: Path,
) -> None:
    """84cf98a379c1's downgrade() must refuse (NotImplementedError) rather
    than silently drop data when a row is in 'queued' or 'interrupted' — a
    status the pre-Phase-4a four-value constraint cannot represent."""
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "downgrade_guard.db"
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    test_db_config: dict = {"type": "sqlite", "path": db_path}

    with patch.dict(app_config.DATABASE_CONFIG, test_db_config, clear=True):
        mgr = DatabaseManager(database_config=test_db_config)
        try:
            now = datetime.now(timezone.utc)
            with mgr.SessionLocal() as session:
                session.add(
                    WorkflowRun(run_type="collection", status="queued", started_at=now)
                )
                session.commit()
        finally:
            mgr.close()

        command.stamp(alembic_cfg, "head")
        with pytest.raises(NotImplementedError):
            command.downgrade(alembic_cfg, "a4d9a4ba00aa")


def test_workflow_stage_attempts_duplicate_attempt_raises(tmp_path: Path) -> None:
    """Duplicate (workflow_run_id, stage_name, attempt_number) must raise."""
    db_path = tmp_path / "duplicate_stage_attempt.db"
    mgr = DatabaseManager(database_config={"type": "sqlite", "path": db_path})
    try:
        now = datetime.now(timezone.utc)
        with mgr.SessionLocal() as session:
            run = WorkflowRun(run_type="refinery", status="running", started_at=now)
            session.add(run)
            session.commit()

            session.add(
                WorkflowStageAttempt(
                    workflow_run_id=run.id,
                    stage_name="draft",
                    attempt_number=1,
                    status="running",
                    started_at=now,
                )
            )
            session.commit()

            session.add(
                WorkflowStageAttempt(
                    workflow_run_id=run.id,
                    stage_name="draft",
                    attempt_number=1,
                    status="running",
                    started_at=now,
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        mgr.close()
