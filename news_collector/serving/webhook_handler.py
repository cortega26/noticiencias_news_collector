"""
Webhook event processing logic.

Handles frontend CI callbacks by updating article publication state
in the database.  Best-effort semantics: failures are logged but
never propagated as HTTP errors to the caller (CI should not block
on backend notification).

Plan 021: matching is keyed by ``event.publication_ids`` (stable
refinery_ids persisted at PR-creation time), not branch equality —
branch/commit_sha remain in the event as audit context only. A
callback with no ``publication_ids`` cannot safely mutate any article
(there is nothing to key the mutation to) and is a no-op, logged as a
warning rather than silently guessed at via branch matching.
"""

from __future__ import annotations

from news_collector.contracts.webhook import (
    PublishCompleteEvent,
    ValidationResultEvent,
)
from news_collector.storage.database import DatabaseManager
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)


def process_validation_result(
    event: ValidationResultEvent,
    db: DatabaseManager,
) -> None:
    """Handle a Content Guard validation result.

    On ``fail``: reject the named publication attempts so the Refinery
    pipeline can re-evaluate them.

    On ``pass``: no action needed (the PR will proceed to deploy).
    """
    if event.status != "fail":
        logger.info(
            "Validation passed for commit {} on branch {} — no action needed",
            event.commit_sha,
            event.branch,
        )
        return

    if not event.publication_ids:
        logger.warning(
            "validation_result 'fail' with no publication_ids — nothing to "
            "reject (branch: {}, commit: {}). Refusing to guess via branch "
            "matching.",
            event.branch,
            event.commit_sha,
        )
        return

    reason = f"Content Guard failed (commit: {event.commit_sha})"
    updated = db.reject_publication_attempts(event.publication_ids, reason=reason)

    if updated == 0:
        logger.warning(
            "No in-flight publication attempts matched publication_ids={} "
            "(branch: {}, commit: {})",
            event.publication_ids,
            event.branch,
            event.commit_sha,
        )
    else:
        logger.info(
            "Rejected {} publication attempt(s) after Content Guard failure "
            "(ids: {}, branch: {}, commit: {})",
            updated,
            event.publication_ids,
            event.branch,
            event.commit_sha,
        )


def process_publish_complete(
    event: PublishCompleteEvent,
    db: DatabaseManager,
) -> None:
    """Handle a successful frontend deployment.

    Completes the named publication attempts, setting ``published_at``/
    ``published_url`` to reflect the live deployment — this is the only
    place those fields get set now that opening a PR no longer implies
    a real deploy.
    """
    deploy_url = _extract_deploy_url(event)
    if not deploy_url:
        logger.warning(
            "No deploy_url found in publish_complete diagnostics — "
            "articles will be marked completed without a URL"
        )

    if not event.publication_ids:
        logger.warning(
            "publish_complete with no publication_ids — nothing to complete "
            "(branch: {}, commit: {}). Refusing to guess via branch matching.",
            event.branch,
            event.commit_sha,
        )
        return

    updated = db.complete_publication_attempts(event.publication_ids, deploy_url)

    if updated == 0:
        logger.warning(
            "No in-flight publication attempts matched publication_ids={} "
            "(branch: {}, commit: {})",
            event.publication_ids,
            event.branch,
            event.commit_sha,
        )
    else:
        logger.info(
            "Marked {} publication attempt(s) LIVE (ids: {}, branch: {}, "
            "deploy_url: {})",
            updated,
            event.publication_ids,
            event.branch,
            deploy_url or "(none)",
        )


def _extract_deploy_url(event: PublishCompleteEvent) -> str | None:
    """Extract the deployment URL from the diagnostics list."""
    for diag in event.diagnostics:
        if diag.check == "deploy" and diag.deploy_url:
            return diag.deploy_url
    return None
