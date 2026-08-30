"""Shared helper for persisting `workflow_runs.run_metadata`.

Both `CollectionRunWorkflow` and `PublicationRunWorkflow` store a pipeline
report dict in the `run_metadata` JSON column. Those reports are deep and can
carry non-JSON leaf types (pydantic models such as `CollectorArticleModel` in
a dry-run selection, datetimes, sets). A finished run losing its bookkeeping
write over a rich leaf type is exactly the durability failure these workflows
exist to prevent — so the write goes through `json_safe()` first.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


def json_safe(value: Any) -> Any:
    """Coerce an arbitrary object graph into something a JSON column can store.

    Dicts/lists recurse; primitives pass through; datetimes become ISO
    strings; pydantic models go through `model_dump(mode="json")`; anything
    else falls back to `str()` — lossy but keeps the row writable.
    """
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return json_safe(model_dump(mode="json"))
    return str(value)
