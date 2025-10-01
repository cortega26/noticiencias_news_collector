"""Tkinter-based configuration editor backed by noticiencias.config_manager."""
from __future__ import annotations

import json
import sys
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Dict

from .config_manager import Config, ConfigError, _is_secret, _diff_configs, load_config, save_config
from .config_schema import DEFAULT_CONFIG, iter_field_docs


@dataclass(slots=True)
class FieldDoc:
    name: str
    description: str
    default: Any
    type_name: str
    is_secret: bool


class ConfigEditor:
    """Small Tkinter wrapper for editing the TOML configuration."""

    def __init__(self, config: Config) -> None:
        self._original_config = config
        self._config = config
        self._data = config.model_dump(mode="python")
        self._field_docs: Dict[str, FieldDoc] = self._build_docs()
        self._widgets: Dict[str, tk.Widget] = {}
        self._variables: Dict[str, tk.Variable] = {}
        self._root = tk.Tk()
        self._root.title("Noticiencias Configuration")
        self._status = tk.StringVar()
        self._search_var = tk.StringVar()
        self._build_ui()
        self._apply_filter()

    def _build_docs(self) -> Dict[str, FieldDoc]:
        docs: Dict[str, FieldDoc] = {}
        for entry in iter_field_docs(DEFAULT_CONFIG):
            if entry.get("is_nested"):
                continue
            name = entry["name"]
            default_value = entry.get("default")
            docs[name] = FieldDoc(
                name=name,
                description=entry.get("description", ""),
                default=default_value,
                type_name=str(entry.get("type", "object")),
                is_secret=_is_secret(name),
            )
        return docs

    def _build_ui(self) -> None:
        container = ttk.Frame(self._root, padding=12)
        container.grid(row=0, column=0, sticky="nsew")
        self._root.rowconfigure(0, weight=1)
        self._root.columnconfigure(0, weight=1)

        notebook = ttk.Notebook(container)
        notebook.grid(row=0, column=0, sticky="nsew")
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        editor_frame = ttk.Frame(notebook, padding=(8, 8, 8, 0))
        help_frame = ttk.Frame(notebook, padding=(8, 8, 8, 0))
        notebook.add(editor_frame, text="Editor")
        notebook.add(help_frame, text="Help")

        self._build_editor(editor_frame)
        self._build_help(help_frame)

    def _build_editor(self, frame: ttk.Frame) -> None:
        toolbar = ttk.Frame(frame)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(1, weight=1)

        ttk.Label(toolbar, text="Filter:").grid(row=0, column=0, padx=(0, 6))
        search_entry = ttk.Entry(toolbar, textvariable=self._search_var)
        search_entry.grid(row=0, column=1, sticky="ew")
        search_entry.bind("<KeyRelease>", lambda _event: self._apply_filter())

        ttk.Button(toolbar, text="Reload", command=self._reload).grid(row=0, column=2, padx=6)
        ttk.Button(toolbar, text="Save", command=self._save).grid(row=0, column=3, padx=6)

        status_label = ttk.Label(frame, textvariable=self._status, foreground="red")
        status_label.grid(row=1, column=0, sticky="ew", pady=(4, 4))

        canvas = tk.Canvas(frame, borderwidth=0)
        scroll_y = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll_y.set)
        canvas.grid(row=2, column=0, sticky="nsew")
        scroll_y.grid(row=2, column=1, sticky="ns")
        frame.rowconfigure(2, weight=1)

        self._form = ttk.Frame(canvas)
        self._form.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._form, anchor="nw")

        for index, name in enumerate(sorted(self._field_docs)):
            self._create_field_row(index, name)

    def _build_help(self, frame: ttk.Frame) -> None:
        search = tk.StringVar()
        ttk.Label(frame, text="Search:").grid(row=0, column=0, padx=(0, 6), pady=(0, 6), sticky="w")
        search_entry = ttk.Entry(frame, textvariable=search)
        search_entry.grid(row=0, column=1, sticky="ew", pady=(0, 6))
        frame.columnconfigure(1, weight=1)

        columns = ("type", "default", "description")
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        for column in columns:
            tree.heading(column, text=column.capitalize())
            tree.column(column, width=200 if column != "description" else 480, anchor="w")
        tree.grid(row=1, column=0, columnspan=2, sticky="nsew")
        frame.rowconfigure(1, weight=1)

        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scrollbar.grid(row=1, column=2, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)

        def refresh_tree(*_args: object) -> None:
            needle = search.get().strip().lower()
            tree.delete(*tree.get_children())
            for doc in self._field_docs.values():
                if needle and needle not in doc.name.lower() and needle not in doc.description.lower():
                    continue
                tree.insert(
                    "",
                    "end",
                    values=(
                        doc.type_name,
                        self._format_display(doc.default),
                        doc.description,
                    ),
                    iid=doc.name,
                    text=doc.name,
                )

        search_entry.bind("<KeyRelease>", refresh_tree)
        refresh_tree()

    def _create_field_row(self, index: int, name: str) -> None:
        doc = self._field_docs[name]
        value = self._resolve_value(name)

        frame = ttk.Frame(self._form)
        frame.grid(row=index, column=0, sticky="ew", pady=4)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text=name).grid(row=0, column=0, padx=(0, 12), sticky="w")

        widget, variable = self._build_widget(frame, doc, value)
        widget.grid(row=0, column=1, sticky="ew")

        if doc.description:
            ttk.Label(frame, text=doc.description, foreground="#555555").grid(
                row=1, column=1, sticky="w", pady=(2, 0)
            )

        self._widgets[name] = widget
        self._variables[name] = variable

    def _build_widget(self, parent: ttk.Frame, doc: FieldDoc, value: Any) -> tuple[tk.Widget, tk.Variable]:
        if isinstance(value, bool):
            var = tk.BooleanVar(value=value)
            widget = ttk.Checkbutton(parent, variable=var)
        else:
            var = tk.StringVar(value=self._format_value(value))
            show = "*" if doc.is_secret else ""
            widget = ttk.Entry(parent, textvariable=var, show=show)
        widget.bind("<FocusOut>", lambda _event, name=doc.name: self._on_change(name))
        return widget, var

    def _format_value(self, value: Any) -> str:
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _format_display(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _resolve_value(self, path: str) -> Any:
        data = self._data
        for part in path.split("."):
            data = data[part]
        return data

    def _apply_filter(self) -> None:
        needle = self._search_var.get().strip().lower()
        for name, widget in self._widgets.items():
            frame = widget.master  # type: ignore[assignment]
            visible = not needle or needle in name.lower() or needle in self._field_docs[name].description.lower()
            frame.grid_remove()
            if visible:
                frame.grid()

    def _on_change(self, name: str) -> None:
        try:
            self._data = self._collect_values()
            self._status.set("")
        except ConfigError as exc:
            self._status.set(str(exc))

    def _collect_values(self) -> Dict[str, Any]:
        updated = self._config.model_dump(mode="python")
        for name, var in self._variables.items():
            if isinstance(var, tk.BooleanVar):
                value = bool(var.get())
            else:
                value = self._parse_value(name, var.get())
            self._assign(updated, name, value)
        return updated

    def _parse_value(self, name: str, raw: str) -> Any:
        default = self._field_docs[name].default
        raw = raw.strip()
        if isinstance(default, int) and not isinstance(default, bool):
            return int(raw)
        if isinstance(default, float):
            return float(raw)
        if isinstance(default, list):
            if raw.startswith("["):
                return json.loads(raw)
            return [part.strip() for part in raw.split(",") if part.strip()]
        if isinstance(default, dict):
            if not raw:
                return {}
            return json.loads(raw)
        if isinstance(default, bool):
            return raw.lower() in {"true", "1", "yes"}
        return raw

    def _assign(self, target: Dict[str, Any], path: str, value: Any) -> None:
        parts = path.split(".")
        node = target
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def _reload(self) -> None:
        try:
            self._config = load_config(getattr(self._config._metadata, "config_path", None))
            self._data = self._config.model_dump(mode="python")
            for name, var in self._variables.items():
                value = self._resolve_value(name)
                if isinstance(var, tk.BooleanVar):
                    var.set(bool(value))
                else:
                    var.set(self._format_value(value))
            self._status.set("Reloaded configuration from disk")
        except ConfigError as exc:
            messagebox.showerror("Reload failed", str(exc))

    def _save(self) -> None:
        try:
            updated_data = self._collect_values()
            new_config = Config.model_validate(updated_data)
            new_config._metadata = self._config._metadata
            before = self._config.model_dump(mode="python")
            after = new_config.model_dump(mode="python")
            path = save_config(new_config)
            diff = _diff_configs(before, after)
            self._config = new_config
            self._data = after
            message = "Saved configuration to {}".format(path)
            if diff:
                message += "\n" + "\n".join(diff)
            messagebox.showinfo("Configuration saved", message)
            self._status.set("")
        except (ConfigError, ValueError) as exc:
            messagebox.showerror("Save failed", str(exc))

    def run(self) -> None:
        self._root.mainloop()


def main(path: str | None = None) -> None:
    try:
        config = load_config(Path(path) if path else None)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    editor = ConfigEditor(config)
    editor.run()


if __name__ == "__main__":  # pragma: no cover - GUI entry point
    target_path = sys.argv[1] if len(sys.argv) > 1 else None
    main(target_path)
