"""Coverage for the non-Tk surface of the Tkinter configuration editor.

Plan 149 item 4: ``noticiencias/gui_config.py`` is a live desktop editor
launched by ``make config-gui`` (verified: Tkinter, not Streamlit — the old
coverage-omit rationale was wrong), and the third writer of ``config.toml``.
Only the widget-building half needs a live Tk root (no display in CI); every
test here builds the editor through ``__new__`` and exercises the pure
helpers plus the save/reload paths with ``save_config``/``load_config`` and
``messagebox`` patched.

The ``tkinter`` import is real in the test venv. The stub fallback in
``_ensure_tkinter`` only activates on hosts whose Python lacks the Tk
bindings, keeping the module importable (and its pure helpers testable)
there as well.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest
from noticiencias.config_manager import Config, ConfigError
from noticiencias.config_schema import DEFAULT_CONFIG


def _ensure_tkinter() -> None:
    """Real Tk bindings when present; attribute-only stub otherwise.

    ``ConfigEditor.__init__`` builds a real Tk root, but nothing here calls
    it, so the stub only has to satisfy ``import tkinter`` and
    ``from tkinter import messagebox, ttk``.
    """
    try:
        import tkinter  # noqa: F401
        import tkinter.messagebox  # noqa: F401
        import tkinter.ttk  # noqa: F401

        return
    except ImportError:  # pragma: no cover - host-dependent fallback
        pass

    tk = types.ModuleType("tkinter")
    for name in ("Widget", "Variable", "StringVar", "BooleanVar", "Tk", "Canvas"):
        setattr(tk, name, type(name, (), {}))
    tk.messagebox = types.ModuleType("tkinter.messagebox")
    tk.ttk = types.ModuleType("tkinter.ttk")
    for name in ("Frame", "Label", "Button", "Entry", "Notebook", "Scrollbar"):
        setattr(tk.ttk, name, type(name, (), {}))
    sys.modules.setdefault("tkinter", tk)
    sys.modules.setdefault("tkinter.messagebox", tk.messagebox)
    sys.modules.setdefault("tkinter.ttk", tk.ttk)


_ensure_tkinter()

import noticiencias.gui_config as gui_config  # noqa: E402


class _Var:
    """Minimal stand-in for a Tk variable (``get``/``set`` only)."""

    def __init__(self, value: str = "") -> None:
        self._value = value

    def get(self) -> str:
        return self._value

    def set(self, value: Any) -> None:
        self._value = value


def _doc(
    name: str = "x", default: Any = 0, *, is_secret: bool = False
) -> gui_config.FieldDoc:
    return gui_config.FieldDoc(
        name=name,
        description=f"Field {name}",
        default=default,
        type_name=type(default).__name__,
        is_secret=is_secret,
    )


def _new_editor(config: Config | None = None) -> gui_config.ConfigEditor:
    """Editor instance without ``__init__`` (which would build a Tk root)."""
    config = config if config is not None else Config()
    editor = gui_config.ConfigEditor.__new__(gui_config.ConfigEditor)
    editor._original_config = config
    editor._config = config
    editor._data = config.model_dump(mode="python")
    editor._field_docs = editor._build_docs()
    editor._widgets = {}
    editor._variables = {}
    editor._choice_mappings = {}
    editor._choice_reverse = {}
    editor._field_groups = {}
    editor._group_descriptions = {}
    editor._status = _Var()
    return editor


class TestFieldDocsAndGrouping:
    def test_build_docs_flags_secrets_from_the_real_schema(self):
        editor = _new_editor()

        assert editor._field_docs["github.token"].is_secret is True
        assert editor._field_docs["news.default_language"].is_secret is False
        assert len(editor._field_docs) > 100

    def test_group_fields_assigns_every_field_exactly_once(self):
        editor = _new_editor()

        groups = editor._group_fields()

        covered = [name for _label, names, _desc in groups for name in names]
        assert sorted(covered) == sorted(editor._field_docs)
        assert len(covered) == len(set(covered))
        assert editor._field_groups["github.token"] in {
            label for label, _names, _desc in groups
        }

    def test_group_fields_falls_back_to_other_for_unknown_prefixes(self):
        editor = _new_editor()
        editor._field_docs["zzz.fake"] = _doc("zzz.fake", 1)

        groups = editor._group_fields()

        other = [names for label, names, _desc in groups if label == "Other"]
        assert other and "zzz.fake" in other[0]

    def test_language_options_merge_defaults_and_config(self):
        editor = _new_editor()

        options = editor._language_options()

        labels = [label for label, _code in options]
        codes = [code for _label, code in options]
        assert labels == sorted(labels)
        assert len(codes) == len(set(codes))
        assert editor._uses_language_dropdown("news.default_language") is True
        assert editor._uses_language_dropdown("database.pool_size") is False


class TestPureHelpers:
    def test_to_serializable_converts_models_paths_and_containers(self):
        editor = _new_editor()

        serializable = editor._to_serializable(
            {
                "model": DEFAULT_CONFIG.app,
                "path": Path("/tmp/config.toml"),
                "tuple": (1, Path("/tmp/x")),
                "nested": [{"k": Path("/tmp/y")}],
            }
        )

        assert isinstance(serializable["model"], dict)
        assert serializable["path"] == "/tmp/config.toml"
        assert serializable["tuple"] == [1, "/tmp/x"]
        assert serializable["nested"] == [{"k": "/tmp/y"}]

    def test_format_value_and_display_render_containers_as_json(self):
        editor = _new_editor()

        assert editor._format_value(None) == ""
        assert editor._format_display(None) == ""
        assert editor._format_value([1, 2]) == "[1, 2]"
        assert editor._format_display({"a": 1}) == '{"a": 1}'
        assert editor._format_value(True) == "True"

    def test_parse_value_uses_choice_mapping_first(self):
        editor = _new_editor()
        editor._choice_mappings["app.lang"] = {"English": "en", "Spanish": "es"}
        editor._field_docs["app.lang"] = _doc("app.lang", "en")

        assert editor._parse_value("app.lang", "Spanish") == "es"
        assert editor._parse_value("app.lang", "") == ""

    def test_parse_value_coerces_by_declared_default_type(self):
        editor = _new_editor()
        editor._field_docs["x.int"] = _doc("x.int", 7)
        editor._field_docs["x.float"] = _doc("x.float", 1.5)
        editor._field_docs["x.bool"] = _doc("x.bool", False)
        editor._field_docs["x.list"] = _doc("x.list", ["a"])
        editor._field_docs["x.dict"] = _doc("x.dict", {"a": 1})
        editor._field_docs["x.optional"] = _doc("x.optional", None)

        assert editor._parse_value("x.int", " 42 ") == 42
        assert editor._parse_value("x.float", "2.5") == 2.5
        assert editor._parse_value("x.bool", "no") is False
        assert editor._parse_value("x.bool", "yes") is True
        assert editor._parse_value("x.list", '["a", "b"]') == ["a", "b"]
        assert editor._parse_value("x.list", "a, b , ") == ["a", "b"]
        assert editor._parse_value("x.dict", '{"k": 2}') == {"k": 2}
        assert editor._parse_value("x.dict", "") == {}
        assert editor._parse_value("x.optional", "") is None
        assert editor._parse_value("x.optional", "none") is None
        assert editor._parse_value("x.optional", "valor") == "valor"

    @pytest.mark.parametrize(
        "name, raw",
        [
            ("x.int", "not-an-int"),
            ("x.float", "not-a-float"),
            ("x.list", "[unclosed"),
            ("x.dict", "{unclosed"),
        ],
    )
    def test_parse_value_rejects_malformed_values(self, name, raw):
        editor = _new_editor()
        editor._field_docs[name] = _doc(
            name,
            {
                "x.int": 0,
                "x.float": 0.0,
                "x.list": [],
                "x.dict": {},
            }[name],
        )

        with pytest.raises(ConfigError):
            editor._parse_value(name, raw)

    def test_assign_and_resolve_nested_paths(self):
        editor = _new_editor()
        target: dict[str, Any] = {}

        editor._assign(target, "a.b.c", 3)

        assert target == {"a": {"b": {"c": 3}}}
        assert editor._resolve_value("database.pool_size") == (
            editor._data["database"]["pool_size"]
        )

    def test_format_choice_label_prefers_reverse_mapping(self):
        editor = _new_editor()
        editor._choice_reverse["app.lang"] = {"en": "English"}

        assert editor._format_choice_label("app.lang", "en") == "English"
        assert editor._format_choice_label("app.lang", None) == ""
        assert editor._format_choice_label("app.lang", 5) == "5"


class TestCollectValuesAndStatus:
    def test_collect_values_round_trips_the_current_config(self):
        editor = _new_editor()

        collected = editor._collect_values()

        assert collected == editor._config.model_dump(mode="python")

    def test_collect_values_parses_every_variable(self):
        editor = _new_editor()
        editor._variables["database.pool_size"] = _Var("42")

        collected = editor._collect_values()

        assert collected["database"]["pool_size"] == 42

    def test_on_change_stores_parse_errors_in_the_status_line(self):
        editor = _new_editor()
        editor._variables["database.pool_size"] = _Var("nope")

        editor._on_change("database.pool_size")

        assert "must be an integer" in editor._status.get()

    def test_on_change_clears_the_status_line_on_success(self):
        editor = _new_editor()
        editor._status.set("previous error")
        editor._variables["database.pool_size"] = _Var("9")

        editor._on_change("database.pool_size")

        assert editor._status.get() == ""
        assert editor._data["database"]["pool_size"] == 9

    def test_apply_filter_uses_name_and_description_matches(self):
        editor = _new_editor()
        editor._field_docs["src.visible"] = _doc("src.visible", "x")
        widget = _FakeWidget()

        editor._widgets["src.visible"] = widget
        editor._search_var = _Var("visible")
        editor._apply_filter()
        assert widget.master.grid_remove_calls == 1
        assert widget.master.grid_calls == 1

        widget.master.reset()
        editor._search_var = _Var("Field src.visible")
        editor._apply_filter()
        assert widget.master.grid_remove_calls == 1
        assert widget.master.grid_calls == 1

        widget.master.reset()
        editor._search_var = _Var("nomatch")
        editor._apply_filter()
        assert widget.master.grid_remove_calls == 1
        assert widget.master.grid_calls == 0


class _FakeFrame:
    def __init__(self) -> None:
        self.grid_remove_calls = 0
        self.grid_calls = 0

    def grid_remove(self) -> None:
        self.grid_remove_calls += 1

    def grid(self) -> None:
        self.grid_calls += 1

    def reset(self) -> None:
        self.grid_remove_calls = 0
        self.grid_calls = 0


class _FakeWidget:
    def __init__(self) -> None:
        self.master = _FakeFrame()


class TestSaveAndReloadPaths:
    def test_save_persists_through_config_manager_and_reports_diff(self, monkeypatch):
        editor = _new_editor()
        editor._variables["database.pool_size"] = _Var("77")
        saved: list[Config] = []
        monkeypatch.setattr(
            gui_config, "save_config", lambda cfg: saved.append(cfg) or Path("/x.toml")
        )
        shown: list[tuple] = []
        monkeypatch.setattr(
            gui_config.messagebox, "showinfo", lambda *a, **k: shown.append(a)
        )

        editor._save()

        assert len(saved) == 1 and saved[0].database.pool_size == 77
        assert shown and "Saved configuration to" in shown[0][1]
        assert editor._config.database.pool_size == 77
        assert editor._status.get() == ""

    def test_save_reports_validation_errors_without_writing(self, monkeypatch):
        editor = _new_editor()
        # -5 fails the schema's lower bound, so it parses fine but the model
        # rejects it (the ValidationError branch).
        editor._variables["database.max_overflow"] = _Var("-5")
        errors: list[tuple] = []
        monkeypatch.setattr(
            gui_config.messagebox, "showerror", lambda *a, **k: errors.append(a)
        )
        monkeypatch.setattr(
            gui_config,
            "save_config",
            lambda cfg: pytest.fail("save_config must not run on invalid input"),
        )

        editor._save()

        assert errors and "Save failed" in errors[0][0]
        assert editor._status.get() != ""

    def test_save_reports_storage_errors(self, monkeypatch):
        editor = _new_editor()
        errors: list[tuple] = []
        monkeypatch.setattr(
            gui_config.messagebox, "showerror", lambda *a, **k: errors.append(a)
        )

        def _boom(_cfg):
            raise ConfigError("disk full")

        monkeypatch.setattr(gui_config, "save_config", _boom)

        editor._save()

        assert errors and errors[0][1] == "disk full"
        assert editor._status.get() == "disk full"

    def test_reload_repopulates_variables_from_disk(self, monkeypatch):
        editor = _new_editor()
        editor._variables["database.pool_size"] = _Var("1")
        reloaded = Config()
        reloaded.database.pool_size = 123
        monkeypatch.setattr(gui_config, "load_config", lambda path: reloaded)

        editor._reload()

        assert editor._variables["database.pool_size"].get() == "123"
        assert editor._status.get() == "Reloaded configuration from disk"

    def test_reload_reports_config_errors(self, monkeypatch):
        editor = _new_editor()
        errors: list[tuple] = []
        monkeypatch.setattr(
            gui_config.messagebox, "showerror", lambda *a, **k: errors.append(a)
        )

        def _boom(_path):
            raise ConfigError("bad toml")

        monkeypatch.setattr(gui_config, "load_config", _boom)

        editor._reload()

        assert errors and errors[0] == ("Reload failed", "bad toml")


class TestMainEntrypoint:
    def test_main_exits_with_stderr_on_config_error(self, monkeypatch, capsys):
        def _boom(_path):
            raise ConfigError("bad toml")

        monkeypatch.setattr(gui_config, "load_config", _boom)

        with pytest.raises(SystemExit) as excinfo:
            gui_config.main("/tmp/config.toml")

        assert excinfo.value.code == 1
        assert "error: bad toml" in capsys.readouterr().err

    def test_main_opens_the_editor(self, monkeypatch):
        config = Config()
        seen: list[Any] = []
        monkeypatch.setattr(gui_config, "load_config", lambda path: config)

        class _FakeEditor:
            def __init__(self, cfg):
                seen.append(cfg)

            def run(self):
                seen.append("run")

        monkeypatch.setattr(gui_config, "ConfigEditor", _FakeEditor)

        gui_config.main(None)

        assert seen == [config, "run"]
