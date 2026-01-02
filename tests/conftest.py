import pytest

from news_collector.storage import database as database_module


@pytest.fixture(autouse=True)
def _close_global_db_manager():
    yield
    manager = getattr(database_module, "_db_manager", None)
    if manager is not None:
        manager.close()
        database_module._db_manager = None
