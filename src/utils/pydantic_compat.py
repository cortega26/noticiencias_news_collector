"""Utilities to obtain a fully-featured Pydantic module during runtime."""

from __future__ import annotations

import importlib
import sys
from functools import lru_cache
from types import ModuleType


def _module_is_usable(module: ModuleType) -> bool:
    """Return True when the module exposes the symbols FastAPI relies on."""

    base_model = getattr(module, "BaseModel", None)
    return bool(
        base_model
        and hasattr(base_model, "model_validate")
        and hasattr(base_model, "model_dump")
        and hasattr(module, "Field")
        and hasattr(module, "field_validator")
        and hasattr(module, "model_validator")
    )


@lru_cache(maxsize=None)
def get_pydantic_module() -> ModuleType:
    """Return a compatible Pydantic module, reloading if a stub was injected."""

    try:
        module = importlib.import_module("pydantic")
    except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
        raise RuntimeError("Pydantic must be installed to run the News Collector") from exc

    if _module_is_usable(module):
        return module

    # A lightweight stub or outdated version was imported. Try reloading the real one.
    sys.modules.pop("pydantic", None)
    module = importlib.import_module("pydantic")
    if not _module_is_usable(module):  # pragma: no cover - indicates incompatible version
        raise RuntimeError(
            "A compatible Pydantic v2 installation is required for validation features"
        )
    return module


__all__ = ["get_pydantic_module"]

