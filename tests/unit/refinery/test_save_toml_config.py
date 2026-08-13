"""Tests for admin_panel.save_toml_config()'s truthful return contract.

Plan 033 Phase 3: save_toml_config() must never claim success it didn't
achieve, and must report version/changed_keys/restart_required_keys so
callers can surface them instead of a blanket "saved" toast.

``apps/refinery/admin_panel.py`` cannot be imported under the test venv
(Streamlit isn't installed there — see
tests/decompose_refinery/test_admin_panel_helpers.py). save_toml_config()
has no Streamlit dependency of its own, so its FunctionDef is extracted via
AST and exec'd with real config_manager/settings collaborators, mirroring
the established pattern in that file.
"""

from __future__ import annotations

import ast
import copy
from pathlib import Path
from typing import Any, Dict

import pytest
from noticiencias.config_manager import Config, ConfigError, load_config, save_config
from pydantic import ValidationError

from news_collector.config import settings as config_settings

ADMIN_PANEL = (
    Path(__file__).resolve().parents[3] / "apps" / "refinery" / "admin_panel.py"
)


@pytest.fixture(autouse=True)
def _restore_runtime_config_snapshot():
    """Restore the runtime config snapshot after each test.

    refresh_runtime_config() mutates module-global state (_CONFIG_STATE /
    _CURRENT_SNAPSHOT). Tests that refresh with a postgres driver leave the
    global pointing at that state; any later test that initializes the DB
    from get_runtime_config() then tries to connect to PostgreSQL and fails
    (pytest-randomly surfaced this by shuffling order, 2026-08-12).
    Resetting _CURRENT_SNAPSHOT to None forces a lazy rebuild on the next
    get_runtime_config() call, returning the repo's real config.
    """
    import news_collector.config.settings as mod

    yield
    mod._CURRENT_SNAPSHOT = None
    mod._CONFIG_STATE = None
    # Rebuild the mutable runtime holder so a later lazy refresh starts
    # from a clean RuntimeSettings (the old RUNTIME may carry a partial
    # config from this file's postgres-driver refresh).
    mod.RUNTIME = type(mod.RUNTIME)()


VALID_TOML = """
[app]
environment = "development"
debug = false

[collection]
request_timeout_seconds = 30

[scoring.weights]
source_credibility = 0.25
recency = 0.25
content_quality = 0.25
engagement_potential = 0.25

[scoring.feature_weights]
source_credibility = 0.25
freshness = 0.25
content_quality = 0.25
engagement = 0.25

[database]
driver = "sqlite"
path = "news.db"
"""


def _load_save_toml_config(config_file: Path):
    """Extract save_toml_config()'s FunctionDef from admin_panel.py and exec it
    with real collaborators, pointed at an isolated config_file."""
    tree = ast.parse(ADMIN_PANEL.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "save_toml_config":
            module = ast.Module(body=[node], type_ignores=[])
            namespace: Dict[str, Any] = {
                "Any": Any,
                "Dict": Dict,
                "Config": Config,
                "ConfigError": ConfigError,
                "ValidationError": ValidationError,
                "load_config": load_config,
                "save_config": save_config,
                "config_settings": config_settings,
                "CONFIG_FILE": config_file,
            }
            exec(compile(module, str(ADMIN_PANEL), "exec"), namespace)  # noqa: S102
            return namespace["save_toml_config"]
    raise AssertionError("save_toml_config not found in admin_panel.py")


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(VALID_TOML, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _restore_runtime_config():
    """save_toml_config() calls the real refresh_runtime_config(); restore
    the process-wide snapshot afterwards so other tests see the real config."""
    yield
    config_settings.refresh_runtime_config()


class TestSuccess:
    def test_valid_save_reports_version_and_success(self, config_file):
        save_toml_config = _load_save_toml_config(config_file)
        config_data = load_config(config_file).model_dump(mode="python")

        result = save_toml_config(config_data)

        assert result["success"] is True
        assert isinstance(result["version"], int)
        assert result["version"] > 0
        assert "restart_required_keys" in result
        assert "changed_keys" in result

    def test_changing_a_live_field_is_reported_in_changed_keys(self, config_file):
        save_toml_config = _load_save_toml_config(config_file)
        config_settings.refresh_runtime_config(load_config(config_file))

        config_data = load_config(config_file).model_dump(mode="python")
        config_data["collection"]["request_timeout_seconds"] = 999

        result = save_toml_config(config_data)

        assert result["success"] is True
        assert "collection_config" in result["changed_keys"]
        assert (
            config_settings.get_runtime_config().collection_config["request_timeout"]
            == 999
        )

    def test_changing_database_driver_is_restart_required(self, config_file):
        save_toml_config = _load_save_toml_config(config_file)
        config_settings.refresh_runtime_config(load_config(config_file))

        config_data = load_config(config_file).model_dump(mode="python")
        config_data["database"] = {
            "driver": "postgresql",
            "host": "localhost",
            "port": 5432,
            "user": "postgres",
            "password": "secret",
            "name": "noticiencias",
        }

        result = save_toml_config(config_data)

        assert result["success"] is True
        assert "database_config" in result["restart_required_keys"]


class TestValidationFailure:
    def test_bad_scoring_weights_fails_without_writing_to_disk(self, config_file):
        save_toml_config = _load_save_toml_config(config_file)
        original_text = config_file.read_text(encoding="utf-8")

        config_data = load_config(config_file).model_dump(mode="python")
        config_data["scoring"]["weights"]["source_credibility"] = 0.9  # sum != 1.0

        result = save_toml_config(config_data)

        assert result["success"] is False
        assert "error" in result
        # The invalid business-rule config must never reach disk.
        assert config_file.read_text(encoding="utf-8") == original_text

    def test_bad_scoring_weights_does_not_touch_live_snapshot(self, config_file):
        save_toml_config = _load_save_toml_config(config_file)
        config_settings.refresh_runtime_config(load_config(config_file))
        before = config_settings.get_runtime_config()

        config_data = load_config(config_file).model_dump(mode="python")
        config_data["scoring"]["weights"]["source_credibility"] = 0.9

        result = save_toml_config(config_data)

        assert result["success"] is False
        after = config_settings.get_runtime_config()
        assert after.version == before.version

    def test_malformed_shape_fails_with_pydantic_error(self, config_file):
        save_toml_config = _load_save_toml_config(config_file)

        config_data = load_config(config_file).model_dump(mode="python")
        config_data["database"] = copy.deepcopy(config_data["database"])
        config_data["database"]["driver"] = "not-a-real-driver"

        result = save_toml_config(config_data)

        assert result["success"] is False
        assert result["error"]
