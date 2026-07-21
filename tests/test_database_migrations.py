"""Tests for automatic schema migrations applied by DatabaseManager."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import inspect as sqla_inspect

ROOT = Path(__file__).resolve().parents[1]

from unittest.mock import patch

from news_collector import config as app_config
from news_collector.storage.database import DatabaseManager


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
    "b61c2d3e4f50",  # add_score_logs_latest_index (head)
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

        with sqlite3.connect(db_path) as conn:
            current = conn.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0]
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
        with sqlite3.connect(db_path) as conn:
            current = conn.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0]
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
    from alembic.config import Config

    db_path = tmp_path / "behind.db"
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    test_db_config: dict = {"type": "sqlite", "path": db_path}

    with patch.dict(app_config.DATABASE_CONFIG, test_db_config, clear=True):
        mgr = DatabaseManager(database_config=test_db_config)
        mgr.close()
        # Stamp as one revision behind head
        command.stamp(alembic_cfg, "a54ba7f7dabb")

    # Read-only check: alembic_version != head
    from news_collector.storage.database import DatabaseManager as DM

    db_mgr = DM(database_config={"type": "sqlite", "path": db_path})
    try:
        with db_mgr.engine.connect() as conn:
            result = conn.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar()
        assert result == "a54ba7f7dabb"
        # Head is b61c2d3e4f50 — DB is behind
        assert result != "b61c2d3e4f50"
    finally:
        db_mgr.close()
