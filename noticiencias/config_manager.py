"""Deterministic configuration loader and CLI for Noticiencias."""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any, Dict, Mapping, MutableMapping, Optional, Sequence

from dotenv import dotenv_values
from pydantic import ValidationError

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - fallback for Py <3.11
    import tomli as tomllib  # type: ignore[no-redef]

try:
    import tomli_w
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    tomli_w = None  # type: ignore[assignment]

from noticiencias.config_schema import Config, DEFAULT_CONFIG, iter_field_docs

DEFAULT_ENV_PREFIX = "NOTICIENCIAS"
DEFAULT_CONFIG_FILENAME = "config.toml"
DEFAULT_ENV_FILENAME = ".env"
BACKUP_DIRNAME = "backups"


@dataclass(frozen=True)
class ConfigValueOrigin:
    """Provenance metadata for a single configuration value."""

    layer: str
    source: str
    env_var: str | None = None
    line: int | None = None

    def render(self) -> str:
        """Return a human-readable provenance description."""

        label = self.layer
        details: list[str] = []
        if self.env_var:
            details.append(self.env_var)
        if self.source:
            details.append(self.source)
        if self.line is not None:
            details.append(f"line {self.line}")
        if details:
            return f"{label} ({', '.join(details)})"
        return label


@dataclass
class ConfigMetadata:
    """Aggregated metadata returned alongside the loaded configuration."""

    config_path: Path
    env_path: Optional[Path]
    env_prefix: str
    provenance: Dict[str, ConfigValueOrigin] = field(default_factory=dict)
    load_order: tuple[str, ...] = (
        "defaults",
        "file",
        "env-file",
        "env",
    )

    def describe_sources(self) -> list[str]:
        sources: list[str] = [
            f"defaults: built into noticiencias.config_schema",  # noqa: E501
            f"config file: {self.config_path}",
        ]
        if self.env_path:
            sources.append(f".env file: {self.env_path}")
        else:
            sources.append(".env file: not found")
        sources.append(f"environment prefix: {self.env_prefix}__*")
        return sources


class ConfigError(RuntimeError):
    """Raised when configuration loading or validation fails."""


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_paths() -> tuple[Path, Path]:
    root = _project_root()
    return root / DEFAULT_CONFIG_FILENAME, root / DEFAULT_ENV_FILENAME


def _deepcopy_mapping(mapping: Mapping[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in mapping.items():
        if isinstance(value, Mapping):
            result[key] = _deepcopy_mapping(value)
        elif isinstance(value, list):
            result[key] = [
                _deepcopy_mapping(item) if isinstance(item, Mapping) else item
                for item in value
            ]
        else:
            result[key] = value
    return result


def _is_secret(path: str) -> bool:
    lowered = path.lower()
    return any(token in lowered for token in ("password", "secret", "token", "key"))


def _merge_layer(
    target: MutableMapping[str, Any],
    updates: Mapping[str, Any],
    provenance: Dict[str, ConfigValueOrigin],
    *,
    origin: ConfigValueOrigin,
    prefix: str = "",
) -> None:
    for key, value in updates.items():
        composed = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            existing = target.get(key)
            if not isinstance(existing, MutableMapping):
                existing = {}
                target[key] = existing
            _merge_layer(existing, value, provenance, origin=origin, prefix=composed)
        else:
            target[key] = value
            provenance[composed] = origin


def _parse_kv_override(raw_key: str, raw_value: str, prefix: str) -> tuple[str, Any]:
    if not raw_key.startswith(prefix + "__"):
        raise ConfigError(
            f"Environment override '{raw_key}' does not start with prefix {prefix}__"
        )
    key_part = raw_key[len(prefix) + 2 :]
    segments = [segment for segment in key_part.split("__") if segment]
    if not segments:
        raise ConfigError(f"Environment override '{raw_key}' is missing key segments")
    path = ".".join(segment.lower() for segment in segments)
    value = _coerce_text(raw_value)
    return path, value


def _coerce_text(value: str) -> Any:
    text = value.strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        try:
            return int(text)
        except ValueError:  # pragma: no cover - defensive
            pass
    try:
        return float(text)
    except ValueError:
        pass
    if (text.startswith("[") and text.endswith("]")) or (
        text.startswith("{") and text.endswith("}")
    ):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return text


def _assign_path(target: MutableMapping[str, Any], path: str, value: Any) -> None:
    segments = path.split(".")
    current: MutableMapping[str, Any] = target
    for segment in segments[:-1]:
        next_value = current.get(segment)
        if not isinstance(next_value, MutableMapping):
            next_value = {}
            current[segment] = next_value
        current = next_value
    current[segments[-1]] = value


def _serialize_for_toml(value: Any) -> Any:
    if isinstance(value, Config):
        data = value.model_dump(mode="python")
        return {key: _serialize_for_toml(val) for key, val in data.items()}
    if value is None:
        # ``tomli_w`` follows the TOML v1.0 specification which does not
        # define a ``null`` value. The project previously stored optional
        # fields as empty strings in ``config.toml`` to signal "unset" values,
        # so we mirror that behaviour here to ensure round-tripping via the
        # GUI keeps parity with the hand-maintained configuration file.
        return ""
    if isinstance(value, Mapping):
        return {key: _serialize_for_toml(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_serialize_for_toml(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=".noticiencias-config-", dir=str(path.parent), delete=False
    ) as tmp_handle:
        tmp_path = Path(tmp_handle.name)
        _dump_toml(payload, tmp_handle)
    try:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        if path.exists():
            backup_dir = path.parent / BACKUP_DIRNAME
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / f"{path.name}.{timestamp}.bak"
            shutil.copy2(path, backup_path)
        os.replace(tmp_path, path)
    except Exception as exc:  # pragma: no cover - defensive
        tmp_path.unlink(missing_ok=True)
        raise ConfigError(f"Failed to persist configuration: {exc}") from exc


def _dump_toml(payload: Mapping[str, Any], handle: IO[bytes]) -> None:
    if tomli_w:
        tomli_w.dump(payload, handle)
        return
    text = _encode_toml(payload)
    handle.write(text.encode("utf-8"))


def _encode_toml(data: Mapping[str, Any], prefix: str = "") -> str:
    lines: list[str] = []
    scalars: Dict[str, Any] = {}
    tables: Dict[str, Mapping[str, Any]] = {}
    for key, value in data.items():
        if isinstance(value, Mapping):
            tables[str(key)] = value
        else:
            scalars[str(key)] = value
    for key, value in scalars.items():
        lines.append(f"{key} = {_format_toml_value(value)}")
    for key, value in tables.items():
        section = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        lines.append("")
        lines.append(f"[{section}]")
        lines.extend(_encode_toml(value, section).splitlines())
    return "\n".join(lines) + "\n"


def _format_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        inner = ", ".join(_format_toml_value(item) for item in value)
        return f"[{inner}]"
    if value is None:
        return '""'
    return json.dumps(str(value))


def _load_toml(path: Path) -> Mapping[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        return {}
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise ConfigError(f"Failed to parse {path}: {exc}") from exc


def _detect_env_path(config_path: Path) -> Path:
    env_candidate = config_path.parent / DEFAULT_ENV_FILENAME
    if env_candidate.exists():
        return env_candidate
    default_config_path, default_env_path = _default_paths()
    if default_env_path.exists():
        return default_env_path
    return env_candidate


def _format_validation_error(
    error: ValidationError,
    provenance: Mapping[str, ConfigValueOrigin],
) -> ConfigError:
    messages: list[str] = []
    for record in error.errors():
        location = ".".join(str(part) for part in record.get("loc", ()))
        origin = provenance.get(location)
        origin_text = f" [{origin.render()}]" if origin else ""
        detail = record.get("msg", "invalid value")
        input_value = record.get("input")
        if input_value is not None and not _is_secret(location):
            detail += f" (received={input_value!r})"
        messages.append(f"{location or '<root>'}: {detail}{origin_text}")
    combined = "\n - ".join(messages)
    return ConfigError(f"Configuration validation failed:\n - {combined}")


def load_config(
    path: Path | None = None,
    *,
    env_prefix: str = DEFAULT_ENV_PREFIX,
    environ: Mapping[str, str] | None = None,
) -> Config:
    """Load configuration by merging defaults, files and environment layers."""

    config_path = path if path else _default_paths()[0]
    env_path = _detect_env_path(config_path)
    runtime_env = environ or os.environ

    defaults = DEFAULT_CONFIG.model_dump(mode="python")
    merged = _deepcopy_mapping(defaults)
    provenance: Dict[str, ConfigValueOrigin] = {}
    default_origin = ConfigValueOrigin(
        layer="defaults",
        source="noticiencias.config_schema.DEFAULT_CONFIG",
    )
    _merge_layer(merged, defaults, provenance, origin=default_origin)

    file_data = _load_toml(config_path)
    if file_data:
        file_origin = ConfigValueOrigin(layer="file", source=str(config_path))
        _merge_layer(merged, file_data, provenance, origin=file_origin)

    env_file_data: Dict[str, str] = {}
    if env_path.exists():
        env_file_data = {
            key: value
            for key, value in dotenv_values(env_path, verbose=False).items()
            if value is not None
        }
        for key, value in env_file_data.items():
            try:
                path_key, parsed_value = _parse_kv_override(key, value, env_prefix)
            except ConfigError:
                continue
            _assign_path(merged, path_key, parsed_value)
            provenance[path_key] = ConfigValueOrigin(
                layer="env-file",
                source=str(env_path),
                env_var=key,
            )

    for key, value in runtime_env.items():
        if not key.startswith(env_prefix + "__"):
            continue
        path_key, parsed_value = _parse_kv_override(key, value, env_prefix)
        _assign_path(merged, path_key, parsed_value)
        provenance[path_key] = ConfigValueOrigin(
            layer="env",
            source="process",
            env_var=key,
        )

    try:
        config = Config.model_validate(merged)
    except ValidationError as exc:
        raise _format_validation_error(exc, provenance) from exc
    config._metadata = ConfigMetadata(
        config_path=config_path,
        env_path=env_path if env_path.exists() else None,
        env_prefix=env_prefix,
        provenance=provenance,
    )
    return config


def save_config(config: Config, path: Path | None = None) -> Path:
    """Persist the provided configuration to disk atomically."""

    metadata = getattr(config, "_metadata", None)
    target_path = path or (metadata.config_path if metadata else _default_paths()[0])
    serialized = _serialize_for_toml(config)
    _write_atomic(target_path, serialized)
    return target_path


def _flatten_mapping(mapping: Mapping[str, Any], prefix: str = "") -> Dict[str, Any]:
    flat: Dict[str, Any] = {}
    for key, value in mapping.items():
        composed = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            flat.update(_flatten_mapping(value, composed))
        else:
            flat[composed] = value
    return flat


def _resolve_value(mapping: Mapping[str, Any], path: str) -> Any:
    current: Any = mapping
    for segment in path.split("."):
        if isinstance(current, Mapping) and segment in current:
            current = current[segment]
        else:
            raise ConfigError(f"Unknown configuration key: {path}")
    return current


def _safe_repr(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return repr(value)


def _diff_configs(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    flat_before = _flatten_mapping(before)
    flat_after = _flatten_mapping(after)
    changes: list[str] = []
    for key in sorted(set(flat_before) | set(flat_after)):
        old = flat_before.get(key)
        new = flat_after.get(key)
        if old == new:
            continue
        if _is_secret(key):
            old_repr = new_repr = "***masked***"
        else:
            old_repr = _safe_repr(old)
            new_repr = _safe_repr(new)
        changes.append(f"{key}: {old_repr} -> {new_repr}")
    return changes


def _format_schema_table() -> str:
    entries = list(iter_field_docs(DEFAULT_CONFIG))
    headers = ["Field", "Type", "Default", "Description", "Constraints", "Example"]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for entry in entries:
        default = ""
        if entry["default"] is not None:
            default = _safe_repr(entry["default"])
        description = entry.get("description", "")
        constraints = entry.get("constraints", "")
        example_values = entry.get("examples", []) or []
        example = ", ".join(str(item) for item in example_values)
        row = [
            entry["name"],
            str(entry["type"]),
            default,
            description,
            constraints,
            example,
        ]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _dump_defaults() -> str:
    payload = _serialize_for_toml(DEFAULT_CONFIG)
    if tomli_w:
        return tomli_w.dumps(payload)
    buffer = io.StringIO()
    buffer.write(_encode_toml(payload))
    return buffer.getvalue()


def _show_sources(metadata: ConfigMetadata) -> str:
    sources = metadata.describe_sources()
    details = "\n".join(f"- {item}" for item in sources)
    return f"Active configuration sources:\n{details}"


def _explain(config: Config, key: str) -> str:
    metadata: ConfigMetadata | None = getattr(config, "_metadata", None)
    if metadata is None:
        raise ConfigError("Configuration metadata is unavailable")
    data = config.model_dump(mode="python")
    value = _resolve_value(data, key)
    origin = metadata.provenance.get(key)
    origin_text = origin.render() if origin else "unknown"
    formatted_value = "***masked***" if _is_secret(key) else _safe_repr(value)
    return f"{key} = {formatted_value}\nsource: {origin_text}"


def _apply_updates(config: Config, updates: Mapping[str, str]) -> Config:
    baseline = config.model_dump(mode="python")
    updated = _deepcopy_mapping(baseline)
    metadata: ConfigMetadata | None = getattr(config, "_metadata", None)
    known_paths = set(_flatten_mapping(baseline).keys())
    for key, raw_value in updates.items():
        if key not in known_paths:
            parent = ".".join(key.split(".")[:-1])
            if parent:
                try:
                    parent_value = _resolve_value(baseline, parent)
                except ConfigError as exc:
                    raise ConfigError(f"Unknown configuration key: {key}") from exc
                if not isinstance(parent_value, Mapping):
                    raise ConfigError(f"Unknown configuration key: {key}")
            else:
                raise ConfigError(f"Unknown configuration key: {key}")
        parsed_value = _coerce_text(raw_value)
        _assign_path(updated, key, parsed_value)
        if metadata:
            metadata.provenance[key] = ConfigValueOrigin(
                layer="cli",
                source="runtime",  # indicates direct CLI override prior to save
            )
    try:
        new_config = Config.model_validate(updated)
    except ValidationError as exc:
        provenance = metadata.provenance if metadata else {}
        raise _format_validation_error(exc, provenance) from exc
    new_config._metadata = metadata
    return new_config


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Noticiencias configuration utilities",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", type=Path, help="Path to the TOML configuration file")
    parser.add_argument(
        "--env-prefix",
        default=DEFAULT_ENV_PREFIX,
        help="Environment variable prefix (e.g. NOTICIENCIAS__COLLECTION__TIMEOUT)",
    )
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--validate", action="store_true", help="Validate the active configuration")
    actions.add_argument("--dump-defaults", action="store_true", help="Print built-in defaults as TOML")
    actions.add_argument("--print-schema", action="store_true", help="Print Markdown table documenting all fields")
    actions.add_argument("--show-sources", action="store_true", help="Show configuration source precedence")
    actions.add_argument("--explain", metavar="KEY", help="Explain where a field value originates")
    actions.add_argument(
        "--set",
        nargs="+",
        metavar="KEY=VALUE",
        help="Apply one or more validated updates and persist them to the config file",
    )

    args = parser.parse_args(argv)

    try:
        if args.dump_defaults:
            sys.stdout.write(_dump_defaults())
            return 0
        if args.print_schema:
            sys.stdout.write(_format_schema_table() + "\n")
            return 0

        config = load_config(args.config, env_prefix=args.env_prefix)
        metadata: ConfigMetadata | None = getattr(config, "_metadata", None)
        if args.validate:
            print("Configuration OK")
            return 0
        if args.show_sources:
            if metadata is None:
                raise ConfigError("Metadata unavailable for source display")
            print(_show_sources(metadata))
            return 0
        if args.explain:
            print(_explain(config, args.explain))
            return 0
        if args.set:
            updates: Dict[str, str] = {}
            for item in args.set:
                if "=" not in item:
                    raise ConfigError(f"Invalid --set argument: '{item}'")
                key, value = item.split("=", 1)
                updates[key.strip()] = value
            new_config = _apply_updates(config, updates)
            before = config.model_dump(mode="python")
            after = new_config.model_dump(mode="python")
            save_path = save_config(new_config, args.config)
            for line in _diff_configs(before, after):
                print(line)
            print(f"Saved configuration to {save_path}")
            return 0
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - module CLI entry point
    raise SystemExit(main())
