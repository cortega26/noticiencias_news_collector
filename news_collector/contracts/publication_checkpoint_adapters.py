"""Adapters from the legacy pipeline result to durable typed item evidence."""

from news_collector.contracts.publication_checkpoint import PublicationItemOutcome


def publication_item_from_result(
    article_id: str, result: dict
) -> PublicationItemOutcome:
    success = result.get("status") == "success" and bool(result.get("processed_count"))
    return PublicationItemOutcome(
        article_id=article_id,
        status=(
            "succeeded"
            if success
            else (
                "waiting_for_image"
                if result.get("status") == "waiting_for_image"
                else "failed"
            )
        ),
        processed_count=int(result.get("processed_count") or 0),
        editorial_completed_count=int(
            result.get("editorial_completed_count", int(success))
        ),
        image_reason=result.get("image_reason"),
        image_brief_slug=result.get("image_brief_slug"),
        pr_url=result.get("pr_url"),
        message=result.get("message"),
        error_code=result.get("error_code"),
    )
