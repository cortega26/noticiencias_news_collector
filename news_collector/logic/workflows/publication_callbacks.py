"""Apply authenticated frontend callbacks to durable publication state.

State mutations require per-post evidence that identifies the exact PR and
the exact markdown bytes tested or deployed. ``publication_ids`` remains the
stable article identity, while attempt references prevent an older callback
from mutating a newer attempt for the same article.
"""

from __future__ import annotations

from typing import Any

from news_collector.contracts.webhook import (
    FrontendWebhookEvent,
    PublishCompleteEvent,
    ValidationResultEvent,
    extract_deploy_url,
)
from news_collector.storage.database import DatabaseManager
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)


def _callback_details(event: FrontendWebhookEvent) -> dict[str, Any]:
    return {
        "event": event.event,
        "status": event.status,
        "commit_sha": event.commit_sha,
        "branch": event.branch,
        "frontend_ref": event.frontend_ref,
        "run_url": event.run_url,
        "checks": [
            {"check": item.check, "status": item.status} for item in event.diagnostics
        ],
    }


def _unmatched_result(event: FrontendWebhookEvent, reason: str) -> dict[str, Any]:
    unmatched = len(set(event.publication_ids))
    result = {
        "action": "unmatched",
        "updated": 0,
        "article_updated": 0,
        "matched": 0,
        "unmatched": unmatched,
        "duplicates": 0,
        "conflicts": 0,
        "needs_attention": bool(unmatched),
        "retryable": reason == "correlated_callback_storage_unavailable",
        "reason": reason,
    }
    logger.warning(
        "Webhook business outcome is unmatched (event={}, reason={}, "
        "publication_ids={}, run_url={}); receipt remains auditable.",
        event.event,
        reason,
        event.publication_ids,
        event.run_url,
    )
    return result


def _attempt_outcome_counts(outcome: Any) -> tuple[int, int, int, int, int, int]:
    return (
        int(outcome.matched),
        int(not outcome.matched),
        int(outcome.transitioned),
        int(outcome.article_updated),
        int(outcome.reason == "already_applied"),
        int(
            outcome.matched
            and not outcome.transitioned
            and outcome.reason != "already_applied"
        ),
    )


def _attempt_callback_action(
    *, updated: int, needs_attention: bool, unmatched: int, target_state: str
) -> str:
    if updated and needs_attention:
        return "partial"
    if updated:
        return "rejected" if target_state == "REJECTED" else "completed"
    if unmatched:
        return "unmatched"
    return "noop"


def _apply_attempt_refs(
    event: FrontendWebhookEvent,
    db: DatabaseManager,
    *,
    target_state: str,
    deploy_url: str | None = None,
) -> dict[str, Any]:
    if not event.publication_ids:
        return {
            "action": "noop",
            "updated": 0,
            "article_updated": 0,
            "matched": 0,
            "unmatched": 0,
            "duplicates": 0,
            "conflicts": 0,
            "needs_attention": False,
            "reason": "no_publication_ids",
        }
    if not event.publication_attempt_refs:
        return _unmatched_result(event, "missing_publication_attempt_refs")

    lifecycle = getattr(db, "lifecycle", None)
    apply_callback = getattr(lifecycle, "apply_correlated_publication_callback", None)
    if not callable(apply_callback):
        return _unmatched_result(event, "correlated_callback_storage_unavailable")

    refs = list(
        {
            (ref.refinery_id, ref.pull_request_number, ref.content_sha256): ref
            for ref in event.publication_attempt_refs
        }.values()
    )
    ref_ids = {ref.refinery_id for ref in refs}
    unmatched = len(set(event.publication_ids) - ref_ids)
    matched = updated = article_updated = duplicates = conflicts = 0
    details = _callback_details(event)
    outcomes: list[dict[str, Any]] = []
    outcome_reasons: list[str] = []

    for ref in refs:
        outcome = apply_callback(
            refinery_id=ref.refinery_id,
            pull_request_number=ref.pull_request_number,
            content_sha256=ref.content_sha256,
            target_state=target_state,
            callback_details=details,
            deploy_url=deploy_url,
        )
        (
            matched_delta,
            unmatched_delta,
            updated_delta,
            article_updated_delta,
            duplicate_delta,
            conflict_delta,
        ) = _attempt_outcome_counts(outcome)
        matched += matched_delta
        unmatched += unmatched_delta
        updated += updated_delta
        article_updated += article_updated_delta
        duplicates += duplicate_delta
        conflicts += conflict_delta
        outcome_reasons.append(outcome.reason)
        outcomes.append(
            {
                "refinery_id": ref.refinery_id,
                "pull_request_number": ref.pull_request_number,
                "attempt_id": outcome.attempt_id,
                "state": outcome.state,
                "transitioned": outcome.transitioned,
                "article_updated": outcome.article_updated,
                "reason": outcome.reason,
            }
        )

    needs_attention = bool(unmatched or conflicts)
    retryable = any(
        reason in {"attempt_not_found", "concurrent_state_change"}
        for reason in outcome_reasons
    )
    if needs_attention:
        logger.warning(
            "Webhook business outcome needs attention (event={}, updated={}, "
            "unmatched={}, conflicts={}, run_url={}).",
            event.event,
            updated,
            unmatched,
            conflicts,
            event.run_url,
        )
    elif updated:
        logger.info(
            "Applied {} {} callback transition(s) across {} article projection(s).",
            updated,
            target_state,
            article_updated,
        )

    action = _attempt_callback_action(
        updated=updated,
        needs_attention=needs_attention,
        unmatched=unmatched,
        target_state=target_state,
    )
    return {
        "action": action,
        "updated": updated,
        "article_updated": article_updated,
        "matched": matched,
        "unmatched": unmatched,
        "duplicates": duplicates,
        "conflicts": conflicts,
        "needs_attention": needs_attention,
        "retryable": retryable,
        "outcomes": outcomes,
        "deploy_url": deploy_url,
    }


def _record_check_passed_events(
    event: ValidationResultEvent, db: DatabaseManager
) -> dict[str, Any]:
    if not event.publication_ids:
        return {
            "action": "noop",
            "updated": 0,
            "matched": 0,
            "unmatched": 0,
            "duplicates": 0,
            "conflicts": 0,
            "needs_attention": False,
            "reason": "no_publication_ids",
        }
    if not event.publication_attempt_refs:
        return _unmatched_result(event, "missing_publication_attempt_refs")

    lifecycle = getattr(db, "lifecycle", None)
    record_pass = getattr(lifecycle, "record_correlated_check_passed", None)
    if not callable(record_pass):
        return _unmatched_result(event, "correlated_callback_storage_unavailable")

    refs = list(
        {
            (ref.refinery_id, ref.pull_request_number, ref.content_sha256): ref
            for ref in event.publication_attempt_refs
        }.values()
    )
    unmatched = len(set(event.publication_ids) - {ref.refinery_id for ref in refs})
    matched = duplicates = conflicts = recorded = 0
    outcomes: list[dict[str, Any]] = []
    outcome_reasons: list[str] = []
    details = _callback_details(event)
    for ref in refs:
        outcome = record_pass(
            refinery_id=ref.refinery_id,
            pull_request_number=ref.pull_request_number,
            content_sha256=ref.content_sha256,
            callback_details=details,
        )
        if outcome.matched:
            matched += 1
        else:
            unmatched += 1
        recorded += int(outcome.recorded)
        if outcome.reason == "already_recorded":
            duplicates += 1
        elif outcome.matched and not outcome.recorded:
            conflicts += 1
        outcome_reasons.append(outcome.reason)
        outcomes.append(
            {
                "refinery_id": ref.refinery_id,
                "pull_request_number": ref.pull_request_number,
                "attempt_id": outcome.attempt_id,
                "state": outcome.state,
                "recorded": outcome.recorded,
                "reason": outcome.reason,
            }
        )

    needs_attention = bool(unmatched or conflicts)
    retryable = any(
        reason in {"attempt_not_found", "concurrent_state_change"}
        for reason in outcome_reasons
    )
    if needs_attention:
        logger.warning(
            "Validation pass callback has unmatched/terminal attempts "
            "(unmatched={}, conflicts={}, run_url={}).",
            unmatched,
            conflicts,
            event.run_url,
        )
    action = (
        "partial"
        if recorded and needs_attention
        else "unmatched" if unmatched else "conflict" if conflicts else "noop"
    )
    return {
        "action": action,
        "updated": 0,
        "recorded": recorded,
        "matched": matched,
        "unmatched": unmatched,
        "duplicates": duplicates,
        "conflicts": conflicts,
        "needs_attention": needs_attention,
        "retryable": retryable,
        "outcomes": outcomes,
        "reason": "validation_passed",
    }


def apply_validation_result(
    event: ValidationResultEvent,
    db: DatabaseManager,
) -> dict[str, Any]:
    """Reject only the exact content attempt that failed validation.

    A pass records correlated audit evidence but does not change publication
    state. Missing or ambiguous references are explicit business outcomes.
    """
    if event.status == "pass":
        return _record_check_passed_events(event, db)
    if event.status != "fail":
        return {"action": "noop", "reason": "validation_status_not_actionable"}
    if not event.publication_ids:
        logger.warning(
            "validation_result fail has no publication_ids (run_url={}); "
            "no publication state changed.",
            event.run_url,
        )
        return {
            "action": "noop",
            "updated": 0,
            "needs_attention": False,
            "reason": "no_publication_ids",
        }

    result = _apply_attempt_refs(event, db, target_state="REJECTED")
    if result["updated"]:
        logger.info(
            "Rejected {} exact publication attempt(s) after Content Guard "
            "failure (commit={}, run_url={}).",
            result["updated"],
            event.commit_sha,
            event.run_url,
        )
    return result


def apply_publish_complete(
    event: PublishCompleteEvent,
    db: DatabaseManager,
) -> dict[str, Any]:
    """Complete only the exact PR artifact whose bytes were deployed."""
    deploy_url = extract_deploy_url(event)
    if not deploy_url:
        logger.warning(
            "No deploy_url found in publish_complete diagnostics; "
            "the exact attempt will be completed without a URL if matched."
        )
    if not event.publication_ids:
        logger.info(
            "publish_complete has no changed publication_ids (run_url={}); "
            "no article transition is needed.",
            event.run_url,
        )
        return {
            "action": "noop",
            "updated": 0,
            "needs_attention": False,
            "reason": "no_publication_ids",
            "deploy_url": deploy_url,
        }

    return _apply_attempt_refs(
        event,
        db,
        target_state="COMPLETED",
        deploy_url=deploy_url,
    )
