"""Module role: Apply authenticated publication callbacks to durable state
(Plan 060 / Phase 5b).

Owns:
- ``apply_validation_result``: on a Content Guard failure, reject the named
  publication attempts so the Refinery pipeline can re-evaluate them; on a
  pass, append a ``check_passed`` audit event for the named attempts.
- ``apply_publish_complete``: complete the named attempts on a real deploy
  (sets ``published_at``/``published_url`` through the legacy projection's
  own transition, which dual-writes the attempt state and its ``deployed``
  event).

Does NOT own:
- Webhook authentication, payload parsing, receipt persistence, duplicate
  replay policy, or retry bookkeeping (`serving/webhook_handler.py`, plan
  5a) — these functions are the *effects* the receipt-first handler applies.
- Delivery identity (`contracts/webhook.py`).
- The legacy article projection and its state filters
  (`storage/article_repository.py`); these functions only drive them.
- Deciding when to replay a stored callback (plan 5b's reconciler does).

Why this lives outside ``serving/``: the reconciler (a workflow consumer)
replays stored callbacks through the same effects and must not import the
serving edge (docs/ARCHITECTURE.md dependency direction).
"""

from __future__ import annotations

from typing import Any, Dict

from news_collector.contracts.webhook import (
    PublishCompleteEvent,
    ValidationResultEvent,
    extract_deploy_url,
)
from news_collector.storage.database import DatabaseManager
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)

_TERMINAL_ATTEMPT_STATES = ("REJECTED", "COMPLETED")


def _record_check_passed_events(
    event: ValidationResultEvent, db: DatabaseManager
) -> None:
    """Best-effort ``check_passed`` audit rows for the named attempts.

    Never raises and never changes the callback's return value: a validation
    pass is a no-op for state, and the audit write must not be able to turn
    that no-op into a processing failure (which would leave the receipt
    ``failed`` and trigger pointless retries).
    """
    lifecycle = getattr(db, "lifecycle", None)
    if lifecycle is None or not event.publication_ids:
        return
    for refinery_id in event.publication_ids:
        try:
            attempt = lifecycle.find_latest_publication_attempt_by_refinery_id(
                refinery_id
            )
            if attempt is None or attempt.state in _TERMINAL_ATTEMPT_STATES:
                continue
            lifecycle.record_publication_event(
                attempt.id,
                event_type="check_passed",
                details={
                    "commit_sha": event.commit_sha,
                    "branch": event.branch,
                    "refinery_id": refinery_id,
                },
            )
        except Exception:
            logger.exception(
                "Could not record check_passed event for refinery_id={} "
                "(callback continues; its outcome is unaffected).",
                refinery_id,
            )


def apply_validation_result(
    event: ValidationResultEvent,
    db: DatabaseManager,
) -> Dict[str, Any]:
    """Handle a Content Guard validation result.

    On ``fail``: reject the named publication attempts so the Refinery
    pipeline can re-evaluate them.

    On ``pass``: no state action (the PR will proceed to deploy); records a
    ``check_passed`` audit event per matching attempt when one exists.

    Plan 021: matching is keyed by ``event.publication_ids`` — never branch
    matching. A callback with no ids cannot safely mutate anything and is a
    labelled no-op.
    """
    if event.status != "fail":
        logger.info(
            "Validation passed for commit {} on branch {} — no action needed",
            event.commit_sha,
            event.branch,
        )
        _record_check_passed_events(event, db)
        return {"action": "noop", "reason": "validation_passed"}

    if not event.publication_ids:
        logger.warning(
            "validation_result 'fail' with no publication_ids — nothing to "
            "reject (branch: {}, commit: {}). Refusing to guess via branch "
            "matching.",
            event.branch,
            event.commit_sha,
        )
        return {"action": "noop", "reason": "no_publication_ids"}

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
    return {"action": "rejected", "updated": updated}


def apply_publish_complete(
    event: PublishCompleteEvent,
    db: DatabaseManager,
) -> Dict[str, Any]:
    """Handle a successful frontend deployment.

    Completes the named publication attempts, setting ``published_at``/
    ``published_url`` to reflect the live deployment — this is the only
    place those fields get set now that opening a PR no longer implies
    a real deploy.
    """
    deploy_url = extract_deploy_url(event)
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
        return {"action": "noop", "reason": "no_publication_ids"}

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
    return {"action": "completed", "updated": updated, "deploy_url": deploy_url}
