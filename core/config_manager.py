"""Configuration manager capable of handling multiple file formats."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, MutableMapping
from ruamel.yaml import YAML

try:  # Python 3.11+
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - fallback for Py <3.11
    import tomli as tomllib  # type: ignore[no-redef]

import tomli_w

from core.config_schema import (
    ConfigFieldSchema,
    ConfigSchema,
    FieldType,
    is_path_key,
    is_secret_key,
)

_LOG_DIR = Path("logs")
_LOG_DIR.mkdir(exist_ok=True)
_LOG_FILE = _LOG_DIR / "config_editor.log"

logging.basicConfig(
    filename=str(_LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
LOGGER = logging.getLogger(__name__)

_BACKUP_DIR = Path("backups")
_BACKUP_DIR.mkdir(exist_ok=True)

_KNOWN_PROFILES = (
    "dev",
    "development",
    "stage",
    "staging",
    "prod",
    "production",
    "test",
    "testing",
)

@dataclass(slots=True)
class ConfigDocument:
    """In-memory representation of the loaded configuration."""

    raw: Any
    profiles: tuple[str, ...]
    path: Path
    fmt: str
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConfigState:
    """Flattened configuration ready for editing."""

    data: "OrderedDict[str, Any]"
    schema: ConfigSchema
    document: ConfigDocument
    profile: str | None


class ConfigError(RuntimeError):
    """Raised when configuration operations cannot be completed."""


class BaseConfigAdapter:
    """Base adapter interface."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> ConfigDocument:
        raise NotImplementedError

    def save(self, document: ConfigDocument) -> None:
        raise NotImplementedError


class YAMLAdapter(BaseConfigAdapter):
    """YAML configuration adapter preserving comments."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self._yaml = YAML()
        self._yaml.preserve_quotes = True
        self._yaml.indent(mapping=2, sequence=4, offset=2)

    def load(self) -> ConfigDocument:
        with self.path.open("r", encoding="utf-8") as handle:
            raw = self._yaml.load(handle) or {}
        profiles = _detect_profiles(raw)
        return ConfigDocument(raw=raw, profiles=profiles, path=self.path, fmt="yaml")

    def save(self, document: ConfigDocument) -> None:
        tmp_path = _write_atomic(self.path, lambda handle: self._yaml.dump(document.raw, handle))
        _create_backup(self.path)
        shutil.move(str(tmp_path), self.path)


class JSONAdapter(BaseConfigAdapter):
    """JSON configuration adapter maintaining stable formatting."""

    def load(self) -> ConfigDocument:
        with self.path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle, object_pairs_hook=OrderedDict)
        profiles = _detect_profiles(raw)
        return ConfigDocument(raw=raw, profiles=profiles, path=self.path, fmt="json")

    def save(self, document: ConfigDocument) -> None:
        def _writer(handle: Any) -> None:
            json.dump(document.raw, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

        tmp_path = _write_atomic(self.path, _writer)
        _create_backup(self.path)
        shutil.move(str(tmp_path), self.path)


class TOMLAdapter(BaseConfigAdapter):
    """TOML configuration adapter."""

    def load(self) -> ConfigDocument:
        with self.path.open("rb") as handle:
            raw = tomllib.load(handle)
        profiles = _detect_profiles(raw)
        return ConfigDocument(raw=raw, profiles=profiles, path=self.path, fmt="toml")

    def save(self, document: ConfigDocument) -> None:
        def _writer(handle: Any) -> None:
            tomli_w.dump(document.raw, handle)

        tmp_path = _write_atomic(self.path, _writer, mode="wb")
        _create_backup(self.path)
        shutil.move(str(tmp_path), self.path)


class EnvAdapter(BaseConfigAdapter):
    """Adapter for ``.env`` files."""

    def load(self) -> ConfigDocument:
        raw_text = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        lines = raw_text.splitlines()
        parsed: "OrderedDict[str, Any]" = OrderedDict()
        entries: list[tuple[str, ...]] = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                entries.append(("comment", line))
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            parsed[key] = value
            entries.append(("pair", key, value))
        profiles: tuple[str, ...] = tuple()
        return ConfigDocument(
            raw=parsed,
            profiles=profiles,
            path=self.path,
            fmt="env",
            extras={"entries": entries},
        )

    def save(self, document: ConfigDocument) -> None:
        entries = document.extras.get("entries", [])
        lines: list[str] = []
        seen_keys: set[str] = set()
        for entry in entries:
            if entry[0] == "comment":
                lines.append(entry[1])
            else:
                key = entry[1]
                seen_keys.add(key)
                value = document.raw.get(key, entry[2])
                lines.append(f"{key}={_stringify_env_value(value)}")
        for key, value in document.raw.items():
            if key not in seen_keys:
                lines.append(f"{key}={_stringify_env_value(value)}")
        content = "\n".join(lines) + ("\n" if lines else "")
        tmp_path = _write_atomic(self.path, lambda handle: handle.write(content))
        _create_backup(self.path)
        shutil.move(str(tmp_path), self.path)


class PythonAdapter(BaseConfigAdapter):
    """Adapter for simple ``config.py`` style files."""

    def load(self) -> ConfigDocument:
        namespace: Dict[str, Any] = {}
        with self.path.open("r", encoding="utf-8") as handle:
            code = compile(handle.read(), str(self.path), "exec")
            exec(code, namespace)  # noqa: S102 - executing trusted config module
        parsed = OrderedDict(
            (key, value)
            for key, value in namespace.items()
            if key.isupper() and not key.startswith("__")
        )
        profiles = _detect_profiles(parsed)
        return ConfigDocument(raw=parsed, profiles=profiles, path=self.path, fmt="py")

    def save(self, document: ConfigDocument) -> None:
        lines = ["# Generated by ConfigManager; existing formatting may change."]
        for key, value in document.raw.items():
            serialized = repr(value)
            lines.append(f"{key} = {serialized}")
        content = "\n".join(lines) + "\n"
        tmp_path = _write_atomic(self.path, lambda handle: handle.write(content))
        _create_backup(self.path)
        shutil.move(str(tmp_path), self.path)


def _detect_profiles(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, Mapping):
        return tuple()
    candidates = [key for key, value in raw.items() if isinstance(value, Mapping)]
    profiles = [key for key in candidates if key.lower() in _KNOWN_PROFILES]
    return tuple(profiles)


def _select_adapter(path: Path) -> BaseConfigAdapter:
    suffix = path.suffix.lower()
    if path.name == ".env" or suffix == ".env":
        return EnvAdapter(path)
    if suffix in {".yaml", ".yml"}:
        return YAMLAdapter(path)
    if suffix == ".json":
        return JSONAdapter(path)
    if suffix == ".toml":
        return TOMLAdapter(path)
    if suffix == ".py":
        return PythonAdapter(path)
    raise ConfigError(f"Unsupported configuration format for {path}")


def _stringify_env_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _write_atomic(path: Path, writer: Any, mode: str = "w") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-config-", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        if "b" in mode:
            with os.fdopen(fd, mode) as handle:
                writer(handle)
        else:
            with os.fdopen(fd, mode, encoding="utf-8") as handle:
                writer(handle)
    except Exception as exc:  # pragma: no cover - defensive
        tmp_path.unlink(missing_ok=True)
        raise ConfigError(f"Failed to write temporary file for {path}") from exc
    return tmp_path


def _create_backup(path: Path) -> None:
    if not path.exists():
        return
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = _BACKUP_DIR / f"{path.name}.{timestamp}.bak"
    shutil.copy2(path, backup_path)


def _flatten(mapping: Mapping[str, Any], parent: str | None = None, sep: str = ".") -> "OrderedDict[str, Any]":
    flat: "OrderedDict[str, Any]" = OrderedDict()
    for key, value in mapping.items():
        composed = f"{parent}{sep}{key}" if parent else str(key)
        if isinstance(value, Mapping):
            nested = _flatten(value, composed, sep)
            flat.update(nested)
        else:
            flat[composed] = value
    return flat


def _unflatten(flat: Mapping[str, Any], sep: str = ".") -> OrderedDict[str, Any]:
    root: OrderedDict[str, Any] = OrderedDict()
    for key, value in flat.items():
        parts = key.split(sep)
        current: MutableMapping[str, Any] = root
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], MutableMapping):
                current[part] = OrderedDict()
            current = current[part]  # type: ignore[assignment]
        current[parts[-1]] = value
    return root


def _infer_field_type(key: str, value: Any) -> FieldType:
    if isinstance(value, bool):
        return FieldType.BOOLEAN
    if isinstance(value, int) and not isinstance(value, bool):
        return FieldType.INTEGER
    if isinstance(value, float):
        return FieldType.FLOAT
    if isinstance(value, str):
        if is_secret_key(key):
            return FieldType.SECRET
        if is_path_key(key):
            return FieldType.PATH
        return FieldType.STRING
    return FieldType.STRING


def _infer_schema(data: Mapping[str, Any], profile: str | None = None) -> ConfigSchema:
    fields = []
    for key, value in data.items():
        field_type = _infer_field_type(key, value)
        schema = ConfigFieldSchema(
            name=key,
            field_type=field_type,
            default=value,
            is_secret=field_type == FieldType.SECRET,
            is_path=field_type == FieldType.PATH,
        )
        fields.append(schema)
    return ConfigSchema(fields=tuple(fields), profile=profile)


def _coerce_value(value: str, schema: ConfigFieldSchema) -> Any:
    if schema.field_type == FieldType.BOOLEAN:
        lowered = value.lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        raise ValueError("Expected a boolean value")
    if schema.field_type == FieldType.INTEGER:
        return int(value)
    if schema.field_type == FieldType.FLOAT:
        return float(value)
    if schema.choices and value not in schema.choices:
        raise ValueError(f"Value must be one of: {', '.join(schema.choices)}")
    return value


def _validate_data(data: Mapping[str, Any], schema: ConfigSchema) -> Dict[str, str]:
    errors: Dict[str, str] = {}
    for field in schema:
        if field.name not in data:
            if field.required:
                errors[field.name] = "Field is required"
            continue
        value = data[field.name]
        try:
            if field.field_type == FieldType.INTEGER:
                int(value)
            elif field.field_type == FieldType.FLOAT:
                float(value)
            elif field.field_type == FieldType.BOOLEAN:
                if isinstance(value, str):
                    _coerce_value(value, field)
                elif not isinstance(value, bool):
                    raise ValueError("Expected boolean")
            elif field.choices and value not in field.choices:
                raise ValueError(f"Must be one of: {', '.join(field.choices)}")
            if field.pattern and isinstance(value, str) and not re.match(field.pattern, value):
                raise ValueError("Value does not match required pattern")
        except ValueError as exc:
            errors[field.name] = str(exc)
    return errors


class ConfigManager:
    """High level configuration management helper."""

    def __init__(self, config_path: Path | str | None = None) -> None:
        self.base_path = Path(config_path).resolve() if config_path else Path.cwd()
        if self.base_path.is_dir():
            self.path = self._detect_source(self.base_path)
        else:
            self.path = self.base_path
        self.adapter = _select_adapter(self.path)
        LOGGER.info("Using configuration source: %s", self.path)
        self._state: ConfigState | None = None

    @staticmethod
    def _detect_source(base_dir: Path) -> Path:
        candidates = [
            base_dir / ".env",
            base_dir / "config.yaml",
            base_dir / "config.yml",
            base_dir / "config.json",
            base_dir / "config.toml",
            base_dir / "config.py",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise ConfigError("No supported configuration source found")

    def load(self, profile: str | None = None) -> ConfigState:
        document = self.adapter.load()
        active_profile = self._resolve_profile(document, profile)
        raw_section = self._get_section(document.raw, active_profile)
        flat = _flatten(raw_section) if isinstance(raw_section, Mapping) else OrderedDict()
        schema = _infer_schema(flat, active_profile)
        state = ConfigState(data=flat, schema=schema, document=document, profile=active_profile)
        self._state = state
        return state

    def _resolve_profile(self, document: ConfigDocument, profile: str | None) -> str | None:
        if not document.profiles:
            return None
        if profile:
            lowered = profile.lower()
            for candidate in document.profiles:
                if candidate.lower() == lowered:
                    return candidate
            raise ConfigError(f"Profile '{profile}' not found in configuration")
        for preferred in ("dev", "development", "default"):
            for candidate in document.profiles:
                if candidate.lower() == preferred:
                    return candidate
        return document.profiles[0]

    def _get_section(self, raw: Any, profile: str | None) -> Mapping[str, Any]:
        if profile is None:
            if isinstance(raw, Mapping):
                return raw
            raise ConfigError("Configuration structure is not a mapping")
        section = raw.get(profile)
        if not isinstance(section, Mapping):
            raise ConfigError(f"Profile '{profile}' does not map to a configuration mapping")
        return section

    def validate(self, data: Mapping[str, Any]) -> Dict[str, str]:
        if not self._state:
            raise ConfigError("Configuration not loaded")
        return _validate_data(data, self._state.schema)

    def save(self, data: Mapping[str, Any]) -> None:
        if not self._state:
            raise ConfigError("Configuration not loaded")
        errors = self.validate(data)
        if errors:
            raise ConfigError(f"Cannot save due to validation errors: {errors}")
        document = self._state.document
        profile = self._state.profile
        updated_tree = _unflatten(OrderedDict(data))
        if profile is None:
            document.raw = _merge_structure(document.raw, updated_tree)
        else:
            if not isinstance(document.raw, MutableMapping):
                raise ConfigError("Cannot update configuration: unexpected structure")
            document.raw[profile] = _merge_structure(document.raw.get(profile, OrderedDict()), updated_tree)
        self.adapter.save(document)
        LOGGER.info("Configuration saved for profile '%s'", profile or "default")

    def set_values(self, updates: Mapping[str, str], profile: str | None = None) -> None:
        state = self.load(profile)
        mutable = OrderedDict(state.data)
        for key, raw_value in updates.items():
            field_schema = state.schema.get(key)
            if not field_schema:
                raise ConfigError(f"Unknown configuration key: {key}")
            try:
                coerced = _coerce_value(str(raw_value), field_schema)
            except ValueError as exc:
                raise ConfigError(f"Invalid value for {key}: {exc}") from exc
            mutable[key] = coerced
        self.save(mutable)

    def available_profiles(self) -> tuple[str, ...]:
        if not self._state:
            state = self.load(None)
        else:
            state = self._state
        return state.document.profiles


def _merge_structure(original: Any, updates: Mapping[str, Any]) -> Any:
    if isinstance(original, MutableMapping):
        target = original
    else:
        target = OrderedDict()
    for key, value in updates.items():
        if isinstance(value, Mapping):
            nested_original = target.get(key, OrderedDict()) if isinstance(target, MutableMapping) else OrderedDict()
            target[key] = _merge_structure(nested_original, value)
        else:
            target[key] = value
    return target
