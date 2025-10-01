"""Project-level versioning and compatibility metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Tuple

MIN_PYTHON_VERSION: Final[Tuple[int, int]] = (3, 10)
MIN_PYTHON_VERSION_STR: Final[str] = ".".join(str(part) for part in MIN_PYTHON_VERSION)
PYTHON_REQUIRES_SPECIFIER: Final[str] = f">={MIN_PYTHON_VERSION_STR}"


@dataclass(frozen=True)
class VersionMetadata:
    """Immutable container for semantic version information."""

    major: int
    minor: int
    patch: int

    def __post_init__(self) -> None:
        for attribute_name, value in (
            ("major", self.major),
            ("minor", self.minor),
            ("patch", self.patch),
        ):
            if value < 0:
                raise ValueError(f"{attribute_name} must be non-negative, got {value}")

    def __str__(self) -> str:  # pragma: no cover - simple formatting helper
        return f"{self.major}.{self.minor}.{self.patch}"

    @property
    def tuple(self) -> Tuple[int, int, int]:
        """Return the version tuple for convenience in tooling."""

        return (self.major, self.minor, self.patch)


PROJECT_VERSION: Final[str] = "1.0.0"
VERSION_INFO: Final[VersionMetadata] = VersionMetadata(
    *tuple(int(part) for part in PROJECT_VERSION.split("."))
)
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
