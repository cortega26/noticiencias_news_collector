"""Pure slugification utility — NFKD-normalize, ASCII-fold, sanitize, dedash."""

from __future__ import annotations

import re
import unicodedata


def slugify(value: str, fallback: str = "article") -> str:
    """Deterministically sanitize *value* into a filesystem-safe slug.

    Applies NFKD normalisation, ASCII encoding, special-character
    replacement, and dash deduplication.  Pure function — no I/O.

    Returns *fallback* when the result would be empty.
    """
    ascii_text = (
        unicodedata.normalize("NFKD", value or "")
        .encode("ascii", "ignore")
        .decode("utf-8")
    )
    ascii_text = re.sub(r"[^a-zA-Z0-9\-_]", "-", ascii_text)
    ascii_text = re.sub(r"-+", "-", ascii_text).strip("-").lower()
    return ascii_text or fallback
