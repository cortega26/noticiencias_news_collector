"""Tkinter configuration editor and CLI entry point."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError as exc:  # pragma: no cover - tkinter unavailable on some platforms
    raise SystemExit("Tkinter is required to run the configuration editor") from exc

from core.config_manager import ConfigError, ConfigManager
from core.config_schema import ConfigFieldSchema, FieldType

LOGGER = logging.getLogger(__name__)
_SETTINGS_PATH = Path.home() / ".noticiencias_config_editor.json"


@dataclass(slots=True)
class FieldWidget:
    """Container holding widget references for a field."""

    widget: tk.Widget
    variable: tk.Variable
    frame: ttk.Frame
    schema: ConfigFieldSchema
    reveal_button: ttk.Button | None = None


class ConfigEditorApp:
    """Tkinter UI wrapper for editing configuration files."""

    def __init__(self, manager: ConfigManager, profile: str | None) -> None:
        self.manager = manager
        self.state = manager.load(profile)
        self.root = tk.Tk()
        self.root.title("Noticiencias Config Editor")
        self._restore_geometry()
        self.root.minsize(720, 480)
        self.root.bind("<Return>", self._handle_enter)
        self.root.bind("<Escape>", self._handle_escape)
        self.root.protocol("WM_DELETE_WINDOW", self._handle_close)

        self.search_var = tk.StringVar()
        self.field_widgets: Dict[str, FieldWidget] = {}
        self.undo_stack: list[OrderedDict[str, Any]] = []
        self.redo_stack: list[OrderedDict[str, Any]] = []
        self.original_data = OrderedDict(self.state.data)
        self.current_data = OrderedDict(self.state.data)
        self.validation_errors: Dict[str, str] = {}

        self._build_ui()
        self._apply_search_filter()
        self._update_save_state()

    # -- UI construction -------------------------------------------------
    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        top_bar = ttk.Frame(container)
        top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        top_bar.columnconfigure(3, weight=1)

        profiles = self.state.document.profiles
        self.profile_var = tk.StringVar(value=self.state.profile or "default")
        if profiles:
            ttk.Label(top_bar, text="Profile:").grid(row=0, column=0, padx=(0, 6))
            self.profile_menu = ttk.Combobox(
                top_bar, values=profiles, textvariable=self.profile_var, state="readonly"
            )
            self.profile_menu.grid(row=0, column=1, padx=(0, 12))
            self.profile_menu.bind("<<ComboboxSelected>>", self._switch_profile)
        else:
            ttk.Label(top_bar, text="Profile: default").grid(row=0, column=0, padx=(0, 12))
            self.profile_menu = None

        ttk.Label(top_bar, text="Search:").grid(row=0, column=2, padx=(0, 6))
        search_entry = ttk.Entry(top_bar, textvariable=self.search_var)
        search_entry.grid(row=0, column=3, sticky="ew")
        search_entry.bind("<KeyRelease>", lambda event: self._apply_search_filter())

        reset_button = ttk.Button(top_bar, text="Reset", command=self._reset_changes)
        reset_button.grid(row=0, column=4, padx=6)

        undo_button = ttk.Button(top_bar, text="Undo", command=self._undo)
        undo_button.grid(row=0, column=5, padx=6)

        redo_button = ttk.Button(top_bar, text="Redo", command=self._redo)
        redo_button.grid(row=0, column=6, padx=6)

        self.save_button = ttk.Button(top_bar, text="Save", command=self._save)
        self.save_button.grid(row=0, column=7, padx=(6, 0))

        self.error_var = tk.StringVar()
        error_label = ttk.Label(container, textvariable=self.error_var, foreground="red")
        error_label.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        canvas = tk.Canvas(container, borderwidth=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        self.form_frame = ttk.Frame(canvas)

        self.form_frame.bind(
            "<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.form_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.grid(row=2, column=0, sticky="nsew")
        scrollbar.grid(row=2, column=1, sticky="ns")
        container.rowconfigure(2, weight=1)

        for row_index, field in enumerate(self.state.schema):
            self._create_field(row_index, field)

    def _create_field(self, row: int, schema: ConfigFieldSchema) -> None:
        frame = ttk.Frame(self.form_frame)
        frame.grid(row=row, column=0, sticky="ew", pady=4)
        frame.columnconfigure(1, weight=1)

        label = ttk.Label(frame, text=schema.name)
        label.grid(row=0, column=0, padx=(0, 12), sticky="w")

        var: tk.Variable
        widget: tk.Widget
        reveal_button: ttk.Button | None = None

        value = self.current_data.get(schema.name, "")
        if schema.field_type == FieldType.BOOLEAN:
            var = tk.BooleanVar(value=bool(value))
            widget = ttk.Checkbutton(frame, variable=var, command=lambda n=schema.name: self._on_boolean_change(n))
        elif schema.field_type == FieldType.INTEGER:
            var = tk.StringVar(value=str(value))
            widget = ttk.Entry(frame, textvariable=var)
            widget.bind("<KeyRelease>", lambda event, n=schema.name: self._on_text_change(n))
            widget.bind("<FocusOut>", lambda event, n=schema.name: self._on_text_change(n))
        elif schema.field_type == FieldType.FLOAT:
            var = tk.StringVar(value=str(value))
            widget = ttk.Entry(frame, textvariable=var)
            widget.bind("<KeyRelease>", lambda event, n=schema.name: self._on_text_change(n))
            widget.bind("<FocusOut>", lambda event, n=schema.name: self._on_text_change(n))
        elif schema.field_type == FieldType.ENUM and schema.choices:
            var = tk.StringVar(value=str(value))
            widget = ttk.Combobox(frame, values=schema.choices, textvariable=var, state="readonly")
            widget.bind("<<ComboboxSelected>>", lambda event, n=schema.name: self._on_text_change(n))
        else:
            var = tk.StringVar(value=str(value))
            widget = ttk.Entry(frame, textvariable=var, show="*" if schema.is_secret else "")
            widget.bind("<FocusOut>", lambda event, n=schema.name: self._on_text_change(n))
            widget.bind("<KeyRelease>", lambda event, n=schema.name: self._on_text_change(n))
            if schema.is_path:
                browse = ttk.Button(frame, text="Browse", command=lambda n=schema.name: self._browse_path(n))
                browse.grid(row=0, column=2, padx=(6, 0))
            if schema.is_secret:
                reveal_button = ttk.Button(
                    frame,
                    text="Reveal",
                    command=lambda w=widget: self._toggle_secret(w),
                    width=8,
                )
                reveal_button.grid(row=0, column=3, padx=(6, 0))

        widget.grid(row=0, column=1, sticky="ew")
        self.field_widgets[schema.name] = FieldWidget(
            widget=widget,
            variable=var,
            frame=frame,
            schema=schema,
            reveal_button=reveal_button,
        )

    # -- Event handlers --------------------------------------------------
    def _on_boolean_change(self, name: str) -> None:
        widget = self.field_widgets[name]
        value = widget.variable.get()
        self._update_value(name, bool(value))

    def _on_text_change(self, name: str) -> None:
        widget = self.field_widgets[name]
        value = widget.variable.get()
        self._update_value(name, value)

    def _browse_path(self, name: str) -> None:
        current = self.current_data.get(name, "")
        if name.lower().endswith("dir") or name.lower().endswith("folder"):
            selected = filedialog.askdirectory(initialdir=current or None)
        else:
            selected = filedialog.askopenfilename(initialdir=current or None)
        if selected:
            widget = self.field_widgets[name]
            widget.variable.set(selected)
            self._update_value(name, selected)

    def _toggle_secret(self, widget: tk.Widget) -> None:
        current = widget.cget("show")
        widget.configure(show="" if current == "*" else "*")

    def _update_value(self, name: str, value: Any) -> None:
        schema = self.field_widgets[name].schema
        converted, error = self._convert_value(value, schema)
        if error:
            self.validation_errors[name] = error
        else:
            self.validation_errors.pop(name, None)
        previous = self.current_data.get(name)
        if error:
            self._update_save_state()
            return
        if converted == previous:
            return
        self.undo_stack.append(OrderedDict(self.current_data))
        self.redo_stack.clear()
        self.current_data[name] = converted
        self._update_save_state()

    def _convert_value(self, value: Any, schema: ConfigFieldSchema) -> tuple[Any, str | None]:
        if schema.field_type == FieldType.BOOLEAN:
            if isinstance(value, bool):
                return value, None
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"true", "1", "yes", "on"}:
                    return True, None
                if lowered in {"false", "0", "no", "off"}:
                    return False, None
            return value, "Invalid boolean"
        if schema.field_type == FieldType.INTEGER:
            text = str(value).strip()
            if not text:
                return value, "Value required"
            try:
                return int(text), None
            except ValueError:
                return value, "Invalid integer"
        if schema.field_type == FieldType.FLOAT:
            text = str(value).strip()
            if not text:
                return value, "Value required"
            try:
                return float(text), None
            except ValueError:
                return value, "Invalid number"
        if schema.choices:
            text = str(value)
            if text not in schema.choices:
                return value, "Select a valid option"
            return text, None
        text = str(value)
        if not text and schema.required:
            return value, "Value required"
        return text, None

    def _reset_changes(self) -> None:
        self.current_data = OrderedDict(self.original_data)
        self.undo_stack.clear()
        self.redo_stack.clear()
        for name, widget in self.field_widgets.items():
            value = self.current_data.get(name, "")
            widget.variable.set(value)
        self.validation_errors.clear()
        self._update_save_state()

    def _undo(self) -> None:
        if not self.undo_stack:
            return
        snapshot = self.undo_stack.pop()
        self.redo_stack.append(OrderedDict(self.current_data))
        self.current_data = snapshot
        self._apply_snapshot(snapshot)
        self._update_save_state()

    def _redo(self) -> None:
        if not self.redo_stack:
            return
        snapshot = self.redo_stack.pop()
        self.undo_stack.append(OrderedDict(self.current_data))
        self.current_data = snapshot
        self._apply_snapshot(snapshot)
        self._update_save_state()

    def _apply_snapshot(self, snapshot: Mapping[str, Any]) -> None:
        for name, widget in self.field_widgets.items():
            widget.variable.set(snapshot.get(name, ""))

    def _switch_profile(self, event: tk.Event) -> None:
        profile = self.profile_var.get()
        if profile == "default":
            profile = None
        self.state = self.manager.load(profile)
        self.original_data = OrderedDict(self.state.data)
        self.current_data = OrderedDict(self.state.data)
        for name, widget in list(self.field_widgets.items()):
            widget.frame.destroy()
        self.field_widgets.clear()
        for row_index, field in enumerate(self.state.schema):
            self._create_field(row_index, field)
        self._apply_search_filter()
        self._update_save_state()

    def _apply_search_filter(self) -> None:
        query = self.search_var.get().strip().lower()
        for name, widget in self.field_widgets.items():
            visible = query in name.lower()
            widget.frame.grid_remove() if not visible else widget.frame.grid()

    def _save(self) -> None:
        try:
            self.manager.save(self.current_data)
        except ConfigError as exc:
            self.error_var.set(str(exc))
            LOGGER.warning("Save failed: %s", exc)
            return
        self.error_var.set("")
        self.original_data = OrderedDict(self.current_data)
        messagebox.showinfo("Config Editor", "Configuration saved successfully")
        self._update_save_state()

    def _update_save_state(self) -> None:
        errors = self.manager.validate(self.current_data)
        errors.update(self.validation_errors)
        if errors:
            first_error = next(iter(errors.values()))
            self.error_var.set(first_error)
        else:
            self.error_var.set("")
        has_changes = self.current_data != self.original_data
        state = tk.NORMAL if not errors and has_changes else tk.DISABLED
        self.save_button.configure(state=state)

    def _handle_enter(self, event: tk.Event) -> None:
        if self.save_button["state"] == tk.NORMAL:
            self._save()

    def _handle_escape(self, event: tk.Event) -> None:
        self._handle_close()

    def _handle_close(self) -> None:
        if self.current_data != self.original_data:
            confirm = messagebox.askyesno("Unsaved Changes", "Discard unsaved changes and close?")
            if not confirm:
                return
        self._persist_geometry()
        self.root.destroy()

    def _restore_geometry(self) -> None:
        if not _SETTINGS_PATH.exists():
            return
        try:
            settings = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        geometry = settings.get("geometry")
        if geometry:
            self.root.geometry(geometry)

    def _persist_geometry(self) -> None:
        data = {"geometry": self.root.geometry()}
        try:
            _SETTINGS_PATH.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            LOGGER.warning("Unable to persist window geometry")

def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Noticiencias configuration editor")
    parser.add_argument("--config", type=str, help="Path to configuration file", default=str(Path.cwd()))
    parser.add_argument("--profile", type=str, help="Configuration profile to use", default=None)
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Headless mode: update a key with the provided value",
    )
    return parser.parse_args(argv)


def run_headless(manager: ConfigManager, updates: list[str], profile: str | None) -> None:
    parsed: Dict[str, str] = {}
    for item in updates:
        if "=" not in item:
            raise ConfigError(f"Invalid --set argument: {item}")
        key, value = item.split("=", 1)
        parsed[key] = value
    manager.set_values(parsed, profile)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv or sys.argv[1:])
    manager = ConfigManager(args.config)
    if args.set:
        run_headless(manager, args.set, args.profile)
        return
    app = ConfigEditorApp(manager, args.profile)
    app.root.mainloop()


if __name__ == "__main__":
    main()
