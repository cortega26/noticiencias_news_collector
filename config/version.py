"""Project-level versioning and compatibility metadata."""

from __future__ import annotations

from pathlib import Path
from typing import Final, Tuple

MIN_PYTHON_VERSION: Final[Tuple[int, int]] = (3, 10)
MIN_PYTHON_VERSION_STR: Final[str] = ".".join(str(part) for part in MIN_PYTHON_VERSION)
PYTHON_REQUIRES_SPECIFIER: Final[str] = f">={MIN_PYTHON_VERSION_STR}"


class VersionMetadata:
    """Immutable container for semantic version information."""

    __slots__ = ("major", "minor", "patch")

    def __init__(self, major: int, minor: int, patch: int) -> None:
        for attribute_name, value in (
            ("major", major),
            ("minor", minor),
            ("patch", patch),
        ):
            if value < 0:
                raise ValueError(f"{attribute_name} must be non-negative, got {value}")
        object.__setattr__(self, "major", major)
        object.__setattr__(self, "minor", minor)
        object.__setattr__(self, "patch", patch)

    def __setattr__(
        self, name: str, value: object
    ) -> None:  # pragma: no cover - enforce immutability
        raise AttributeError("VersionMetadata instances are read-only")

    def __str__(self) -> str:  # pragma: no cover - simple formatting helper
        return f"{self.major}.{self.minor}.{self.patch}"

    @property
    def tuple(self) -> Tuple[int, int, int]:
        """Return the version tuple for convenience in tooling."""

        return (self.major, self.minor, self.patch)


_VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
PROJECT_VERSION: Final[str] = _VERSION_FILE.read_text(encoding="utf-8").strip()
_VERSION_PARTS: Tuple[int, int, int] = tuple(
    int(part) for part in PROJECT_VERSION.split(".")
)
VERSION_INFO: Final[VersionMetadata] = VersionMetadata(*_VERSION_PARTS)
__version__: Final[str] = PROJECT_VERSION

__all__ = [
    "MIN_PYTHON_VERSION",
    "MIN_PYTHON_VERSION_STR",
    "PYTHON_REQUIRES_SPECIFIER",
    "PROJECT_VERSION",
    "VERSION_INFO",
    "__version__",
    "VersionMetadata",
]
