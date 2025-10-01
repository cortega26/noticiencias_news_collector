"""Utility classes for describing configuration schemas."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Optional


class FieldType(str, Enum):
    """Enumeration of supported configuration field types."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    PATH = "path"
    SECRET = "secret"
    ENUM = "enum"


@dataclass(slots=True)
class ConfigFieldSchema:
    """Metadata describing a single configuration field."""

    name: str
    field_type: FieldType
    description: str | None = None
    default: Any | None = None
    required: bool = True
    choices: tuple[str, ...] | None = None
    pattern: str | None = None
    is_secret: bool = False
    is_path: bool = False

    def copy_with(self, **overrides: Any) -> "ConfigFieldSchema":
        """Return a copy of the schema with selected fields overridden."""

        data = self.__dict__ | overrides
        return ConfigFieldSchema(**data)


@dataclass(slots=True)
class ConfigSchema:
    """Container holding schema definitions for a configuration profile."""

    fields: tuple[ConfigFieldSchema, ...]
    profile: str | None = None

    def field_names(self) -> tuple[str, ...]:
        """Return the ordered field names."""

        return tuple(field.name for field in self.fields)

    def get(self, name: str) -> Optional[ConfigFieldSchema]:
        """Fetch a field by name."""

        for field in self.fields:
            if field.name == name:
                return field
        return None

    def __iter__(self) -> Iterable[ConfigFieldSchema]:
        return iter(self.fields)


def is_secret_key(key: str) -> bool:
    """Return ``True`` when the key looks like it contains a secret value."""

    lowered = key.lower()
    return any(token in lowered for token in ("key", "token", "secret", "password"))


def is_path_key(key: str) -> bool:
    """Return ``True`` when the key appears to reference a filesystem path."""

    lowered = key.lower()
    return any(token in lowered for token in ("path", "dir", "file", "folder", "socket"))
