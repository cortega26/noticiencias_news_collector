"""Dict-backed attribute-access wrapper for safe null-tolerant field access."""

from __future__ import annotations

from typing import Any


class SafeNamespace:
    """Wrap a dict as an object so missing attributes return None instead of raising.

    Use for safe null-tolerant field access on article-like payloads.
    """

    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)

    def __getattr__(self, name: str) -> None:
        return None
