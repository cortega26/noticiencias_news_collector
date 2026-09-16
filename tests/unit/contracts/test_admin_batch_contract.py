"""Contract tests for batch publication shapes (Plan 109).

Pure boundary validation: no DB, no I/O. Invalid payloads must fail at
the Pydantic boundary (HTTP 422) rather than inside the workflow.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from news_collector.contracts.admin import (
    BATCH_MAX_IDS,
    AdminPublishBatchItem,
    AdminPublishBatchRequest,
    AdminPublishBatchStarted,
)


def test_batch_cap_is_five() -> None:
    assert BATCH_MAX_IDS == 5


def test_valid_single_and_full_batch() -> None:
    assert AdminPublishBatchRequest(article_ids=[7]).article_ids == [7]
    full = AdminPublishBatchRequest(article_ids=[1, 2, 3, 4, 5])
    assert full.article_ids == [1, 2, 3, 4, 5]


def test_empty_batch_rejected() -> None:
    with pytest.raises(ValidationError):
        AdminPublishBatchRequest(article_ids=[])


def test_oversize_batch_rejected() -> None:
    with pytest.raises(ValidationError):
        AdminPublishBatchRequest(article_ids=[1, 2, 3, 4, 5, 6])


def test_duplicate_ids_rejected_explicitly() -> None:
    """Duplicates fail loudly (LAW-B6) instead of publishing twice."""
    with pytest.raises(ValidationError, match="duplicates"):
        AdminPublishBatchRequest(article_ids=[3, 3])


def test_non_positive_ids_rejected() -> None:
    with pytest.raises(ValidationError, match="positive"):
        AdminPublishBatchRequest(article_ids=[0])
    with pytest.raises(ValidationError, match="positive"):
        AdminPublishBatchRequest(article_ids=[-2])


def test_batch_item_shape() -> None:
    item = AdminPublishBatchItem(
        article_id=9,
        status="succeeded",
        pr_url="https://example.com/pr/1",
        final_slug="s",
    )
    assert item.failure_class is None
    with pytest.raises(ValidationError):
        AdminPublishBatchItem(article_id=9, status="maybe")


def test_batch_started_carries_accepted_ids() -> None:
    started = AdminPublishBatchStarted(
        run_id="12", status="queued", detail="d", accepted_ids=[1, 2]
    )
    assert started.accepted_ids == [1, 2]
    assert AdminPublishBatchStarted(run_id="12", detail="d").accepted_ids == []
