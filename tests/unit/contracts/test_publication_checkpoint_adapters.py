"""Pipeline outcomes keep editorial work separate from actual PR creation."""

import pytest

from news_collector.contracts.publication_checkpoint import PublicationItemOutcome
from news_collector.contracts.publication_checkpoint_adapters import (
    publication_item_from_result,
)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            {
                "status": "success",
                "processed_count": 1,
                "pr_url": "https://example.org/pr/1",
            },
            PublicationItemOutcome(
                article_id="3822",
                status="succeeded",
                processed_count=1,
                editorial_completed_count=1,
                pr_url="https://example.org/pr/1",
            ),
        ),
        (
            {
                "status": "waiting_for_image",
                "processed_count": 0,
                "editorial_completed_count": 1,
                "image_reason": "unproven_image_rights",
                "image_brief_slug": "roots-and-fungi",
                "message": "Edición completada · esperando imagen",
            },
            PublicationItemOutcome(
                article_id="3822",
                status="waiting_for_image",
                editorial_completed_count=1,
                image_reason="unproven_image_rights",
                image_brief_slug="roots-and-fungi",
                message="Edición completada · esperando imagen",
            ),
        ),
        (
            {
                "status": "error",
                "error_code": "E_EDITORIAL_VALUE_ADD",
                "message": "The editorial gate rejected the draft",
            },
            PublicationItemOutcome(
                article_id="3822",
                status="failed",
                error_code="E_EDITORIAL_VALUE_ADD",
                message="The editorial gate rejected the draft",
            ),
        ),
        (
            {"status": "success", "processed_count": 0},
            PublicationItemOutcome(article_id="3822", status="failed"),
        ),
    ],
    ids=[
        "pr-created",
        "editorial-complete-media-pending",
        "editorial-rejection",
        "no-pr",
    ],
)
def test_result_mapping_preserves_per_article_outcome(result, expected):
    assert publication_item_from_result("3822", result) == expected


def test_invalid_pipeline_counter_is_not_hidden_as_a_successful_outcome():
    with pytest.raises(ValueError):
        publication_item_from_result(
            "3822", {"status": "success", "processed_count": "not-a-count"}
        )
