"""El .env de respaldo del repo se puede reemplazar (aislamiento de tests)."""

from __future__ import annotations

from pathlib import Path

import pytest
from noticiencias import config_manager


def test_override_reemplaza_el_env_de_respaldo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    custom = tmp_path / "custom.env"
    monkeypatch.setenv(config_manager.DEFAULT_ENV_PATH_OVERRIDE, str(custom))

    assert config_manager._default_paths()[1] == custom


def test_sin_override_usa_el_env_del_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(config_manager.DEFAULT_ENV_PATH_OVERRIDE, raising=False)

    expected = config_manager._project_root() / config_manager.DEFAULT_ENV_FILENAME
    assert config_manager._default_paths()[1] == expected


def test_un_env_local_no_se_filtra_en_configs_temporales(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")

    config = config_manager.load_config(config_path, environ={})

    assert abs(sum(config.scoring.weights.model_dump().values()) - 1.0) < 0.01
