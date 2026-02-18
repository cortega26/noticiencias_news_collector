"""Tests for NewsCollectorSystem initialization behavior."""

import pytest

# Global path/module hacking removed in favor of proper testing environment
# If fastapi is missing, we should handle it in the test setup or ensure dev deps are installed.
# For now, we assume proper environment setup via make bootstrap.

pytestmark = pytest.mark.e2e


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
