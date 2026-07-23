"""
Plan 017 — Bulk article action helper.

A pure, testable helper for running a batch of per-article operations
with continue-on-error semantics and a structured success/failure report.
Does NOT depend on Streamlit, git, or any I/O — the caller injects the
per-item callable.

The divergence bug from the rejected UI slice is fixed here: the helper
never touches DB rows until the per-item callable succeeds, and each
item's result is captured independently (no batched commit/push that can
leave the system in a partially-applied state).

Usage:
    from apps.refinery.bulk_helper import run_bulk, BulkResult

    result = run_bulk(
        items=[{"refinery_id": "2026-01-15-a"}, {"refinery_id": "2026-01-16-b"}],
        action=lambda item: delete_one(item),
        batch_cap=5,
    )
    # result.succeeded -> list of items
    # result.failed -> list of (item, error_message)
    # result.summary -> "2 succeeded, 0 failed"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

T = TypeVar("T")


@dataclass
class BulkFailure:
    """A single item that failed during the bulk operation."""

    item: Any
    error: str


@dataclass
class BulkResult:
    """Structured result of a bulk operation."""

    succeeded: list[Any] = field(default_factory=list)
    failed: list[BulkFailure] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.succeeded) + len(self.failed)

    @property
    def summary(self) -> str:
        return f"{len(self.succeeded)} succeeded, {len(self.failed)} failed"

    @property
    def all_succeeded(self) -> bool:
        return len(self.failed) == 0


def run_bulk(
    items: list[T],
    action: Callable[[T], Any],
    batch_cap: int = 5,
) -> BulkResult:
    """
    Run a per-item action on each item in ``items`` with continue-on-error
    semantics.

    - If an item's action raises, the error is captured and the loop
      continues to the next item (no abort).
    - The DB/filesystem are never touched until the action succeeds —
      the caller's ``action`` is responsible for the full per-item
      lifecycle (find, delete file, commit, push, delete DB rows).
    - The batch is capped at ``batch_cap`` items; excess items are
      ignored and a note is added to the first failure.

    Args:
        items: The list of items to process.
        action: A callable that takes one item and performs the per-item
                operation. If it raises, the item is recorded as failed.
        batch_cap: Maximum number of items to process.

    Returns:
        A :class:`BulkResult` with succeeded/failed lists.
    """
    result = BulkResult()

    if len(items) > batch_cap:
        result.failed.append(
            BulkFailure(
                item=None,
                error=(
                    f"Batch size {len(items)} exceeds cap {batch_cap}. "
                    f"Only the first {batch_cap} items will be processed."
                ),
            )
        )
        items = items[:batch_cap]

    for item in items:
        try:
            action(item)
            result.succeeded.append(item)
        except Exception as exc:
            result.failed.append(BulkFailure(item=item, error=str(exc)))

    return result
