"""
Webhook event processing logic.

Handles frontend CI callbacks by updating article publication state
in the database.  Best-effort semantics: failures are logged but
never propagated as HTTP errors to the caller (CI should not block
on backend notification).
"""

from __future__ import annotations

from datetime import datetime, timezone

from news_collector.contracts.webhook import (
    PublishCompleteEvent,
    ValidationResultEvent,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)


def process_validation_result(
    event: ValidationResultEvent,
    db: DatabaseManager,
) -> None:
    """Handle a Content Guard validation result.

    On ``fail``: mark articles in 'publishing'/'validated' state for
    the matching branch as 'rejected' so the Refinery pipeline can
    re-evaluate them.

    On ``pass``: no action needed (the PR will proceed to deploy).
    """
    if event.status != "fail":
        logger.info(
            "Validation passed for commit {} on branch {} — no action needed",
            event.commit_sha,
            event.branch,
        )
        return

    updated = 0
    with db.get_session() as session:
        candidates = (
            session.query(Article)
            .filter(Article.processing_status.in_(["publishing", "validated"]))
            .all()
        )
        for article in candidates:
            metadata = article.article_metadata or {}
            if metadata.get("publishing_branch") == event.branch:
                article.processing_status = "rejected"
                updated += 1

    if updated == 0:
        logger.warning(
            "No articles found in publishing/validated state for branch {}",
            event.branch,
        )
    else:
        logger.info(
            "Marked {} articles as rejected after Content Guard failure "
            "(branch: {}, commit: {})",
            updated,
            event.branch,
            event.commit_sha,
        )


def process_publish_complete(
    event: PublishCompleteEvent,
    db: DatabaseManager,
) -> None:
    """Handle a successful frontend deployment.

    Updates articles from 'publishing'/'validated' to 'completed',
    setting ``published_at`` and ``published_url`` to reflect the
    live deployment.
    """
    deploy_url = _extract_deploy_url(event)
    if not deploy_url:
        logger.warning(
            "No deploy_url found in publish_complete diagnostics — "
            "articles will be marked completed without a URL"
        )

    now = datetime.now(timezone.utc)
    updated = 0
    with db.get_session() as session:
        candidates = (
            session.query(Article)
            .filter(Article.processing_status.in_(["publishing", "validated"]))
            .all()
        )
        for article in candidates:
            metadata = article.article_metadata or {}
            if metadata.get("publishing_branch") == event.branch:
                article.processing_status = "completed"
                article.published_at = now
                if deploy_url:
                    article.published_url = deploy_url
                updated += 1

    if updated == 0:
        logger.warning(
            "No articles found in publishing/validated state for branch {} "
            "(commit: {})",
            event.branch,
            event.commit_sha,
        )
    else:
        logger.info(
            "Marked {} articles as LIVE (branch: {}, deploy_url: {})",
            updated,
            event.branch,
            deploy_url or "(none)",
        )


def _extract_deploy_url(event: PublishCompleteEvent) -> str | None:
    """Extract the deployment URL from the diagnostics list."""
    for diag in event.diagnostics:
        if diag.check == "deploy" and diag.deploy_url:
            return diag.deploy_url
    return None
