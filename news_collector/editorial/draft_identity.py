"""Pure cache identity for prepared editorial work; media is a separate dependency."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

EDITORIAL_DRAFT_VERSION = "editorial-draft-evidence-v2"
_MEDIA_KEYS = frozenset(
    {"image", "image_url", "image_alt", "image_origin", "image_caption", "image_credit"}
)


def _editorial_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): _editorial_value(v)
            for k, v in value.items()
            if k not in _MEDIA_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_editorial_value(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def editorial_fingerprint(article: dict, settings: dict) -> str:
    """Hash explicit input/config snapshots; never store provider credentials."""
    encoded = json.dumps(
        [EDITORIAL_DRAFT_VERSION, _editorial_value(article), settings],
        sort_keys=True,
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
