"""Project-level versioning and compatibility metadata."""
from __future__ import annotations

from typing import Final, Tuple

MIN_PYTHON_VERSION: Final[Tuple[int, int]] = (3, 10)
MIN_PYTHON_VERSION_STR: Final[str] = ".".join(str(part) for part in MIN_PYTHON_VERSION)
PYTHON_REQUIRES_SPECIFIER: Final[str] = f">={MIN_PYTHON_VERSION_STR}"

__all__ = [
    "MIN_PYTHON_VERSION",
    "MIN_PYTHON_VERSION_STR",
    "PYTHON_REQUIRES_SPECIFIER",
]
