"""Tkinter-based configuration editor backed by noticiencias.config_manager."""

from __future__ import annotations

import json
import sys
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Dict, Iterable, List, Tuple

from pydantic import BaseModel

from .config_manager import (
    Config,
    ConfigError,
    _diff_configs,
    _is_secret,
    load_config,
    save_config,
)
from .config_schema import DEFAULT_CONFIG, iter_field_docs


@dataclass(slots=True)
class FieldDoc:
    name: str
    description: str
    default: Any
    type_name: str
    is_secret: bool


@dataclass(frozen=True)
class FieldGroup:
    """Logical grouping metadata for configuration fields."""

    label: str
    prefixes: Tuple[str, ...]
    description: str = ""


FIELD_GROUPS: Tuple[FieldGroup, ...] = (
    FieldGroup(
        label="General",
        prefixes=(
            "app.",
            "paths.",
            "collection.",
            "rate_limiting.",
            "robots.",
            "news.",
        ),
        description=(
            "Deployment, filesystem, and collection scheduling controls "
            "used across the application."
        ),
    ),
    FieldGroup(
        label="Database",
        prefixes=("database.",),
        description="Connectivity parameters for SQL backends.",
    ),
    FieldGroup(
        label="Scoring & Weights",
        prefixes=("scoring.",),
        description="Tuning knobs for the article scoring pipeline.",
    ),
    FieldGroup(
        label="Text Processing",
        prefixes=("text_processing.",),
        description="Normalization and penalty configuration for textual content.",
    ),
    FieldGroup(
        label="Enrichment",
        prefixes=("enrichment.",),
        description="Entity, topic, and NLP enrichment options.",
    ),
    FieldGroup(
        label="Deduplication",
        prefixes=("dedup.",),
        description="Similarity thresholds and cluster sizing.",
    ),
    FieldGroup(
        label="Formats & Logging",
        prefixes=("logging.",),
        description="Output formatting and retention for structured logs.",
    ),
)


LANGUAGE_LABELS: Dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "pt": "Portuguese",
    "fr": "French",
}


class ConfigEditor:
    """Small Tkinter wrapper for editing the TOML configuration."""

    def __init__(self, config: Config) -> None:
        self._original_config = config
        self._config = config
        self._data = config.model_dump(mode="python")
        self._field_docs: Dict[str, FieldDoc] = self._build_docs()
        self._widgets: Dict[str, tk.Widget] = {}
        self._variables: Dict[str, tk.Variable] = {}
        self._choice_mappings: Dict[str, Dict[str, Any]] = {}
        self._choice_reverse: Dict[str, Dict[str, str]] = {}
        self._field_groups: Dict[str, str] = {}
        self._group_descriptions: Dict[str, str] = {}
        self._root = tk.Tk()
        self._root.title("Noticiencias Configuration")
        self._status = tk.StringVar()
        self._search_var = tk.StringVar()
        self._build_ui()
        self._apply_filter()

    def _to_serializable(self, value: Any) -> Any:
        """Return a JSON-serializable representation of *value*."""

        if isinstance(value, BaseModel):
            return self._to_serializable(value.model_dump(mode="python"))
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {key: self._to_serializable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._to_serializable(item) for item in value]
        if isinstance(value, tuple):
            return [self._to_serializable(item) for item in value]
        return value

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

    def _language_options(self) -> List[Tuple[str, str]]:
        codes: set[str] = set()
        for config in (DEFAULT_CONFIG, self._config):
            codes.update(getattr(config.text_processing, "supported_languages", []))
            codes.add(getattr(config.news, "default_language", ""))
            for model in getattr(config.enrichment, "models", {}).values():
                codes.update(getattr(model, "languages", []))
                default_language = getattr(model, "default_language", "")
                if default_language:
                    codes.add(default_language)
        cleaned_codes = [code for code in codes if code]
        options = [
            (LANGUAGE_LABELS.get(code, code.upper()), code) for code in cleaned_codes
        ]
        return sorted(options, key=lambda item: item[0])

    def _format_choice_label(self, name: str, value: Any) -> str:
        reverse = self._choice_reverse.get(name, {})
        if value in reverse:
            return reverse[value]
        if isinstance(value, str) and value in reverse:
            return reverse[value]
        if value is None:
            return ""
        if isinstance(value, str):
            return LANGUAGE_LABELS.get(value, value)
        return str(value)

    def _uses_language_dropdown(self, name: str) -> bool:
        return name.endswith("default_language")

    def _build_ui(self) -> None:
        container = ttk.Frame(self._root, padding=12)
        container.grid(row=0, column=0, sticky="nsew")
        self._root.rowconfigure(0, weight=1)
        self._root.columnconfigure(0, weight=1)

        toolbar = ttk.Frame(container)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(1, weight=1)

        ttk.Label(toolbar, text="Filter:").grid(row=0, column=0, padx=(0, 6))
        search_entry = ttk.Entry(toolbar, textvariable=self._search_var)
        search_entry.grid(row=0, column=1, sticky="ew")
        search_entry.bind("<KeyRelease>", lambda _event: self._apply_filter())

        ttk.Button(toolbar, text="Reload", command=self._reload).grid(
            row=0, column=2, padx=6
        )
        ttk.Button(toolbar, text="Save", command=self._save).grid(
            row=0, column=3, padx=6
        )

        status_label = ttk.Label(container, textvariable=self._status, foreground="red")
        status_label.grid(row=1, column=0, sticky="ew", pady=(4, 4))

        notebook = ttk.Notebook(container)
        notebook.grid(row=2, column=0, sticky="nsew")
        container.rowconfigure(2, weight=1)
        container.columnconfigure(0, weight=1)

        self._group_containers: Dict[str, ttk.Frame] = {}
        self._forms: Dict[str, ttk.Frame] = {}

        for label, names, description in self._group_fields():
            group_frame = ttk.Frame(notebook, padding=(8, 8, 8, 0))
            notebook.add(group_frame, text=label)
            self._group_containers[label] = group_frame
            self._forms[label] = self._build_group_form(group_frame, names, description)

        help_frame = ttk.Frame(notebook, padding=(8, 8, 8, 0))
        notebook.add(help_frame, text="Help")
        self._build_help(help_frame)

    def _group_fields(self) -> List[Tuple[str, List[str], str]]:
        groups: List[Tuple[str, List[str], str]] = []
        assigned: set[str] = set()
        for group in FIELD_GROUPS:
            names = sorted(
                name
                for name in self._field_docs
                if any(name.startswith(prefix) for prefix in group.prefixes)
            )
            if names:
                groups.append((group.label, names, group.description))
                assigned.update(names)
        remaining = sorted(name for name in self._field_docs if name not in assigned)
        if remaining:
            groups.append(("Other", remaining, "Fields without a dedicated category."))
        self._field_groups = {
            name: label for label, items, _ in groups for name in items
        }
        self._group_descriptions = {
            label: description for label, _items, description in groups
        }
        return groups

    def _build_group_form(
        self, frame: ttk.Frame, names: Iterable[str], description: str
    ) -> ttk.Frame:
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        if description:
            ttk.Label(frame, text=description, wraplength=680).grid(
                row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
            )

        canvas = tk.Canvas(frame, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")

        form = ttk.Frame(canvas)
        form.columnconfigure(0, weight=1)
        form.bind(
            "<Configure>",
            lambda event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        window_id = canvas.create_window((0, 0), window=form, anchor="nw")
        canvas.bind(
            "<Configure>",
            lambda event, item=window_id: canvas.itemconfigure(item, width=event.width),
        )

        for index, name in enumerate(names):
            self._create_field_row(form, index, name)

        return form

    def _build_help(self, frame: ttk.Frame) -> None:
        search = tk.StringVar()
        ttk.Label(frame, text="Search:").grid(
            row=0, column=0, padx=(0, 6), pady=(0, 6), sticky="w"
        )
        search_entry = ttk.Entry(frame, textvariable=search)
        search_entry.grid(row=0, column=1, sticky="ew", pady=(0, 6))
        frame.columnconfigure(1, weight=1)

        columns = ("field", "type", "default", "group", "description")
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        for column in columns:
            tree.heading(column, text=column.capitalize())
            if column == "description":
                tree.column(column, width=560, anchor="w")
            elif column == "default":
                tree.column(column, width=220, anchor="w")
            elif column == "group":
                tree.column(column, width=160, anchor="w")
            elif column == "field":
                tree.column(column, width=260, anchor="w")
            else:
                tree.column(column, width=140, anchor="w")
        tree.grid(row=1, column=0, columnspan=2, sticky="nsew")
        frame.rowconfigure(1, weight=1)

        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scrollbar.grid(row=1, column=2, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)

        def refresh_tree(*_args: object) -> None:
            needle = search.get().strip().lower()
            tree.delete(*tree.get_children())
            for name in sorted(self._field_docs):
                doc = self._field_docs[name]
                group_label = self._field_groups.get(name, "Other")
                haystacks = (
                    doc.name.lower(),
                    doc.description.lower(),
                    group_label.lower(),
                )
                if needle and not any(needle in haystack for haystack in haystacks):
                    continue
                tree.insert(
                    "",
                    "end",
                    values=(
                        doc.name,
                        doc.type_name,
                        self._format_display(doc.default),
                        group_label,
                        doc.description,
                    ),
                    iid=doc.name,
                    text=doc.name,
                )

        search_entry.bind("<KeyRelease>", refresh_tree)
        refresh_tree()

    def _create_field_row(self, parent: ttk.Frame, index: int, name: str) -> None:
        doc = self._field_docs[name]
        value = self._resolve_value(name)

        frame = ttk.Frame(parent)
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

    def _build_widget(
        self, parent: ttk.Frame, doc: FieldDoc, value: Any
    ) -> tuple[tk.Widget, tk.Variable]:
        if self._uses_language_dropdown(doc.name):
            options = self._language_options()
            mapping: Dict[str, str] = {label: code for label, code in options}
            reverse: Dict[str, str] = {code: label for label, code in options}
            if isinstance(value, str) and value and value not in reverse:
                reverse[value] = LANGUAGE_LABELS.get(value, value)
                mapping[reverse[value]] = value
            display_value: str
            if value is None:
                display_value = ""
            else:
                raw_value = value if isinstance(value, str) else str(value)
                display_value = reverse.get(
                    raw_value, LANGUAGE_LABELS.get(raw_value, raw_value)
                )
                if display_value not in mapping and raw_value:
                    mapping[display_value] = raw_value
                    reverse[raw_value] = display_value
            values = list(mapping.keys())
            var = tk.StringVar(value=display_value)
            widget = ttk.Combobox(
                parent, textvariable=var, values=values, state="readonly"
            )
            widget.bind(
                "<<ComboboxSelected>>",
                lambda _event, name=doc.name: self._on_change(name),
            )
            self._choice_mappings[doc.name] = mapping
            self._choice_reverse[doc.name] = reverse
            return widget, var
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
        if value is None:
            return ""
        serializable = self._to_serializable(value)
        if isinstance(serializable, (list, dict)):
            try:
                return json.dumps(serializable, ensure_ascii=False)
            except TypeError:
                return str(value)
        return str(serializable)

    def _format_display(self, value: Any) -> str:
        if value is None:
            return ""
        serializable = self._to_serializable(value)
        if isinstance(serializable, (list, dict)):
            try:
                return json.dumps(serializable, ensure_ascii=False)
            except TypeError:
                return str(value)
        return str(serializable)

    def _resolve_value(self, path: str) -> Any:
        data = self._data
        for part in path.split("."):
            data = data[part]
        return data

    def _apply_filter(self) -> None:
        needle = self._search_var.get().strip().lower()
        for name, widget in self._widgets.items():
            frame = widget.master  # type: ignore[assignment]
            visible = (
                not needle
                or needle in name.lower()
                or needle in self._field_docs[name].description.lower()
            )
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
        raw = raw.strip()
        if name in self._choice_mappings:
            mapping = self._choice_mappings[name]
            if not raw:
                return ""
            return mapping.get(raw, raw)
        default = self._field_docs[name].default
        if raw == "" and default is None:
            return None
        if raw.lower() == "none" and default is None:
            return None
        if isinstance(default, int) and not isinstance(default, bool):
            try:
                return int(raw)
            except ValueError as exc:
                raise ConfigError(f"{name} must be an integer") from exc
        if isinstance(default, float):
            try:
                return float(raw)
            except ValueError as exc:
                raise ConfigError(f"{name} must be a number") from exc
        if isinstance(default, list):
            if raw.startswith("["):
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ConfigError(f"{name} must be valid JSON") from exc
            return [part.strip() for part in raw.split(",") if part.strip()]
        if isinstance(default, dict):
            if not raw:
                return {}
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ConfigError(f"{name} must be valid JSON") from exc
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
            self._config = load_config(
                getattr(self._config._metadata, "config_path", None)
            )
            self._data = self._config.model_dump(mode="python")
            for name, var in self._variables.items():
                value = self._resolve_value(name)
                if isinstance(var, tk.BooleanVar):
                    var.set(bool(value))
                elif name in self._choice_mappings:
                    var.set(self._format_choice_label(name, value))
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
        raise SystemExit(1) from exc
    editor = ConfigEditor(config)
    editor.run()


if __name__ == "__main__":  # pragma: no cover - GUI entry point
    target_path = sys.argv[1] if len(sys.argv) > 1 else None
    main(target_path)
