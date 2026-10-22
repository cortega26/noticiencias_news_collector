"""Publication may wait for media without extending collection run states."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from news_collector.contracts.admin import (
    AdminCollectStarted,
    AdminCollectStatus,
    AdminPublishBatchItem,
    AdminPublishBatchStarted,
    AdminPublishStarted,
    AdminPublishStatus,
)


@pytest.mark.parametrize(
    "contract", [AdminPublishStarted, AdminPublishBatchStarted, AdminPublishStatus]
)
def test_publication_contract_accepts_waiting_for_image(contract) -> None:
    value = contract.model_validate(
        {"run_id": "99", "status": "waiting_for_image", "detail": "waiting"}
    )
    assert value.status == "waiting_for_image"


@pytest.mark.parametrize("contract", [AdminCollectStarted, AdminCollectStatus])
def test_collection_contract_does_not_accept_publication_waiting(contract) -> None:
    with pytest.raises(ValidationError):
        contract.model_validate(
            {"run_id": "99", "status": "waiting_for_image", "detail": "waiting"}
        )


def test_batch_item_preserves_image_dependency() -> None:
    item = AdminPublishBatchItem.model_validate(
        {
            "article_id": 3822,
            "status": "waiting_for_image",
            "image_reason": "missing_source_image",
            "image_brief_slug": "roots-3822",
        }
    )
    assert item.image_reason == "missing_source_image"
    assert item.image_brief_slug == "roots-3822"
    assert item.pr_url is None
