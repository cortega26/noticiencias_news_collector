"""Real SQLite sessions for legacy pipeline tests with injected collaborators."""

from contextlib import contextmanager
from pathlib import Path

from news_collector.storage.database import DatabaseManager


def sqlite_workflow_sessions(path: Path):
    """Open/close each session owner while retaining the durable test database."""

    @contextmanager
    def session():
        manager = DatabaseManager({"type": "sqlite", "path": path})
        try:
            with manager.get_session() as transaction:
                yield transaction
        finally:
            manager.close()

    return session
