"""GUI persistence integration tests for the configuration editor."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest
import tkinter as tk

from noticiencias.config_manager import Config, load_config, save_config, main as config_cli_main
from noticiencias.config_schema import DEFAULT_CONFIG
from noticiencias.gui_config import ConfigEditor


class _StringVarStub:
    """Minimal stub mirroring :class:`tkinter.StringVar`."""

    def __init__(self, value: str | None = None) -> None:
        self._value = value or ""

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value


class _BooleanVarStub:
    """Minimal stub mirroring :class:`tkinter.BooleanVar`."""

    def __init__(self, value: bool | None = None) -> None:
        self._value = bool(value)

    def get(self) -> bool:
        return self._value

    def set(self, value: bool) -> None:
        self._value = bool(value)


@pytest.fixture()
def tk_runtime_shim(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide lightweight tkinter stubs to run the editor without a display."""

    root_surrogate = SimpleNamespace(
        title=lambda *_args, **_kwargs: None,
        rowconfigure=lambda *_args, **_kwargs: None,
        columnconfigure=lambda *_args, **_kwargs: None,
        mainloop=lambda: None,
    )

    monkeypatch.setattr(tk, "Tk", lambda: root_surrogate)
    monkeypatch.setattr(tk, "StringVar", _StringVarStub)
    monkeypatch.setattr(tk, "BooleanVar", _BooleanVarStub)


@pytest.fixture()
def editor_factory(monkeypatch: pytest.MonkeyPatch, tk_runtime_shim: None) -> Callable[[Config], ConfigEditor]:
    """Return a helper that instantiates :class:`ConfigEditor` with stubs."""

    def _factory(config: Config) -> ConfigEditor:
        def _fake_build_ui(self: ConfigEditor) -> None:
            self._variables["database.connect_timeout"] = tk.StringVar(
                value=str(self._resolve_value("database.connect_timeout"))
            )
            self._variables["collection.async_enabled"] = tk.BooleanVar(
                value=bool(self._resolve_value("collection.async_enabled"))
            )

        monkeypatch.setattr(ConfigEditor, "_build_ui", _fake_build_ui)
        monkeypatch.setattr(ConfigEditor, "_apply_filter", lambda self: None)
        monkeypatch.setattr(
            "noticiencias.gui_config.messagebox.showinfo", lambda *_args, **_kwargs: None
        )
        monkeypatch.setattr(
            "noticiencias.gui_config.messagebox.showerror", lambda *_args, **_kwargs: None
        )
        return ConfigEditor(config)

    return _factory


def _write_config(path: Path, connect_timeout: int, async_enabled: bool) -> Config:
    """Persist a config copy with updated values to *path* and return it."""

    config_data = DEFAULT_CONFIG.model_copy(deep=True).model_dump(mode="python")
    config_data["database"]["connect_timeout"] = connect_timeout
    config_data["collection"]["async_enabled"] = async_enabled
    config = Config.model_validate(config_data)
    save_config(config, path)
    return load_config(path)


def test_editor_save_persists_and_cli_reads(
    tmp_path: Path,
    editor_factory: Callable[[Config], ConfigEditor],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Saving through the GUI writes changes that the CLI subsequently observes."""

    config_path = tmp_path / "config.toml"
    initial_config = _write_config(config_path, connect_timeout=10, async_enabled=False)
    editor = editor_factory(initial_config)

    editor._variables["database.connect_timeout"].set("42")
    async_var = editor._variables["collection.async_enabled"]
    async_var.set(not async_var.get())

    editor._save()

    reloaded = load_config(config_path)
    assert reloaded.database.connect_timeout == 42
    assert reloaded.collection.async_enabled is True

    exit_code = config_cli_main(
        ["--config", str(config_path), "--explain", "database.connect_timeout"]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "database.connect_timeout = 42" in captured.out
    assert "source: file" in captured.out


def test_editor_reload_applies_disk_changes(
    tmp_path: Path, editor_factory: Callable[[Config], ConfigEditor]
) -> None:
    """Reloading repopulates editor fields from the persisted configuration."""

    config_path = tmp_path / "config.toml"
    initial_config = _write_config(config_path, connect_timeout=15, async_enabled=False)
    editor = editor_factory(initial_config)

    updated_config = initial_config.model_copy(deep=True)
    updated_config.database.connect_timeout = 99
    updated_config.collection.async_enabled = True
    updated_config._metadata = initial_config._metadata
    save_config(updated_config, config_path)

    editor._reload()

    assert editor._variables["database.connect_timeout"].get() == "99"
    assert editor._variables["collection.async_enabled"].get() is True
