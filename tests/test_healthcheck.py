"""Tests for the CLI healthcheck utility."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.storage.database import DatabaseManager
from src.storage.models import Article


@pytest.fixture()
def healthcheck_db(tmp_path):
    """Create a temporary database populated with an old article."""

    db_path = tmp_path / "healthcheck.db"
    manager = DatabaseManager(database_config={"type": "sqlite", "path": db_path})

    old_timestamp = datetime.now(timezone.utc) - timedelta(hours=2)
    with manager.get_session() as session:
        article = Article(
            url="https://example.com/stale",
            title="Artículo antiguo",
            summary="Contenido mínimo para healthcheck.",
            source_id="test_source",
            source_name="Test Source",
            category="science",
            collected_date=old_timestamp,
            processing_status="completed",
        )
        session.add(article)

    return manager


def test_healthcheck_failure_exit_code(monkeypatch, healthcheck_db):
    """The CLI should exit with non-zero status when ingest lag exceeds threshold."""

    import scripts.healthcheck as healthcheck

    monkeypatch.setattr(healthcheck, "get_database_manager", lambda: healthcheck_db)

    with pytest.raises(SystemExit) as excinfo:
        healthcheck.main(["--max-ingest-minutes", "0", "--max-pending", "50"])

    assert excinfo.value.code == 1
