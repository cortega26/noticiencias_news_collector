"""Tests for NewsCollectorSystem initialization behavior."""

import sys
import types
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Provide a lightweight FastAPI stub to satisfy imports during testing
fastapi_stub = types.ModuleType("fastapi")


class _StubFastAPI:
    def __init__(self, *args, **kwargs):  # pragma: no cover - simple stub
        self.routes = []

    def get(
        self, *decorator_args, **decorator_kwargs
    ):  # pragma: no cover - simple stub
        def decorator(func):
            self.routes.append(("GET", decorator_args, decorator_kwargs, func))
            return func

        return decorator


class _StubHTTPException(Exception):
    def __init__(self, status_code: int = 500, detail: str | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


fastapi_stub.FastAPI = _StubFastAPI
fastapi_stub.HTTPException = _StubHTTPException
fastapi_stub.Depends = lambda dependency=None: dependency
fastapi_stub.Query = lambda default=None, alias=None: default

sys.modules.setdefault("fastapi", fastapi_stub)

pytestmark = pytest.mark.e2e

import main
from main import NewsCollectorSystem


class MockModuleLogger:
    """Simple logger stub that records messages for assertions."""

    def __init__(self):
        self.infos = []
        self.warnings = []
        self.errors = []

    def info(self, message):
        self.infos.append(message)

    def warning(self, message):
        self.warnings.append(message)

    def error(self, message):
        self.errors.append(message)


class MockLogger:
    """Logger factory stub used to capture module logs."""

    def __init__(self):
        self.modules = {}
        self.startup_logged = False
        self.errors = []

    def log_system_health(self):
        return None

    def create_module_logger(self, module_name: str):
        if module_name not in self.modules:
            self.modules[module_name] = MockModuleLogger()
        return self.modules[module_name]

    def log_system_startup(self, **_kwargs):
        self.startup_logged = True

    def log_error_with_context(self, error, context=None):
        self.errors.append((error, context))


class MockDatabaseManager:
    """Minimal database manager stub for initialization tests."""

    config = {"type": "stub"}

    def __init__(self, failed_sources: int = 1):
        self.failed_sources = failed_sources
        self.initialized_with_sources = None

    def initialize_sources(self, sources):
        self.initialized_with_sources = sources

    def get_health_status(self):
        return {"failed_sources": self.failed_sources, "status": "degraded"}


class MockCollector:
    """Collector stub reporting healthy status."""

    def is_healthy(self) -> bool:
        return True


def test_initialize_with_failed_sources_warning(monkeypatch):
    """Initialization should continue when only failed sources are reported."""

    test_logger = MockLogger()

    monkeypatch.setattr(main, "setup_logging", lambda: test_logger)
    mock_db_manager = MockDatabaseManager()
    monkeypatch.setattr(main, "get_database_manager", lambda: mock_db_manager)
    monkeypatch.setattr(main, "RSSCollector", lambda: MockCollector())

    def fake_setup_scoring(self):
        self.scorer = object()
        self.logger.create_module_logger("scoring").info("Scoring stub configurado")

    monkeypatch.setattr(NewsCollectorSystem, "_setup_scoring", fake_setup_scoring)

    system = NewsCollectorSystem()
    assert system.initialize() is True

    database_logger = test_logger.modules.get("database")
    assert database_logger is not None
    assert any(
        isinstance(event, dict)
        and event.get("event") == "database.health.warning"
        and event.get("details", {}).get("failed_sources") == 1
        for event in database_logger.warnings
    )

    system_logger = test_logger.modules.get("system")
    assert system_logger is not None
    assert any(
        isinstance(event, dict) and event.get("event") == "system.initialize.warning"
        for event in system_logger.warnings
    )
