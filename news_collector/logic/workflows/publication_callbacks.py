"""Apply authenticated frontend callbacks to durable publication state.

State mutations require per-post evidence that identifies the exact PR and
the exact markdown bytes tested or deployed. ``publication_ids`` remains the
stable article identity, while attempt references prevent an older callback
from mutating a newer attempt for the same article.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from news_collector.contracts.webhook import (
    FrontendWebhookEvent,
    PublishCompleteEvent,
    ValidationResultEvent,
    extract_deploy_url,
)
from news_collector.storage.database import DatabaseManager
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)


@dataclass(frozen=True)
class _PreparedAttemptCallback:
    refs: list[Any]
    apply: Callable[..., Any]
    unmatched: int


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


def _no_publication_ids_result(*, include_article_updated: bool) -> dict[str, Any]:
    result = {
        "action": "noop",
        "updated": 0,
        "matched": 0,
        "unmatched": 0,
        "duplicates": 0,
        "conflicts": 0,
        "needs_attention": False,
        "reason": "no_publication_ids",
    }
    if include_article_updated:
        result["article_updated"] = 0
    return result


def _prepare_attempt_callback(
    event: FrontendWebhookEvent, db: DatabaseManager, storage_method: str
) -> _PreparedAttemptCallback | dict[str, Any]:
    if not event.publication_attempt_refs:
        return _unmatched_result(event, "missing_publication_attempt_refs")

    lifecycle = getattr(db, "lifecycle", None)
    apply = getattr(lifecycle, storage_method, None)
    if not callable(apply):
        return _unmatched_result(event, "correlated_callback_storage_unavailable")

    refs = list(
        {
            (ref.refinery_id, ref.pull_request_number, ref.content_sha256): ref
            for ref in event.publication_attempt_refs
        }.values()
    )
    unmatched = len({*event.publication_ids} - {ref.refinery_id for ref in refs})
    return _PreparedAttemptCallback(refs=refs, apply=apply, unmatched=unmatched)


def _track_attempt_outcome(
    counts: dict[str, int],
    outcomes: list[dict[str, Any]],
    reasons: list[str],
    ref: Any,
    outcome: Any,
) -> None:
    values = _attempt_outcome_counts(outcome)
    for key, value in zip(
        (
            "matched",
            "unmatched",
            "updated",
            "article_updated",
            "duplicates",
            "conflicts",
        ),
        values,
        strict=True,
    ):
        counts[key] += value
    reasons.append(outcome.reason)
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


def _log_attempt_callback_outcome(
    event: FrontendWebhookEvent,
    target_state: str,
    counts: dict[str, int],
    needs_attention: bool,
) -> None:
    if needs_attention:
        logger.warning(
            "Webhook business outcome needs attention (event={}, updated={}, "
            "unmatched={}, conflicts={}, run_url={}).",
            event.event,
            counts["updated"],
            counts["unmatched"],
            counts["conflicts"],
            event.run_url,
        )
    elif counts["updated"]:
        logger.info(
            "Applied {} {} callback transition(s) across {} article projection(s).",
            counts["updated"],
            target_state,
            counts["article_updated"],
        )


def _retryable_callback(reasons: list[str]) -> bool:
    return any(
        reason in {"attempt_not_found", "concurrent_state_change"} for reason in reasons
    )


def _apply_one_attempt_callback(
    prepared: _PreparedAttemptCallback,
    ref: Any,
    *,
    target_state: str,
    deploy_url: str | None,
    details: dict[str, Any],
    counts: dict[str, int],
    outcomes: list[dict[str, Any]],
    reasons: list[str],
) -> None:
    outcome = prepared.apply(
        refinery_id=ref.refinery_id,
        pull_request_number=ref.pull_request_number,
        content_sha256=ref.content_sha256,
        target_state=target_state,
        callback_details=details,
        deploy_url=deploy_url,
    )
    _track_attempt_outcome(counts, outcomes, reasons, ref, outcome)


def _attempt_callback_result(
    event: FrontendWebhookEvent,
    target_state: str,
    deploy_url: str | None,
    counts: dict[str, int],
    outcomes: list[dict[str, Any]],
    reasons: list[str],
) -> dict[str, Any]:
    needs_attention = bool(counts["unmatched"] or counts["conflicts"])
    _log_attempt_callback_outcome(event, target_state, counts, needs_attention)
    return {
        "action": _attempt_callback_action(
            updated=counts["updated"],
            needs_attention=needs_attention,
            unmatched=counts["unmatched"],
            target_state=target_state,
        ),
        **counts,
        "needs_attention": needs_attention,
        "retryable": _retryable_callback(reasons),
        "outcomes": outcomes,
        "deploy_url": deploy_url,
    }


def _apply_attempt_refs(
    event: FrontendWebhookEvent,
    db: DatabaseManager,
    *,
    target_state: str,
    deploy_url: str | None = None,
) -> dict[str, Any]:
    if not event.publication_ids:
        return _no_publication_ids_result(include_article_updated=True)
    prepared = _prepare_attempt_callback(
        event, db, "apply_correlated_publication_callback"
    )
    if isinstance(prepared, dict):
        return prepared

    counts = {
        "matched": 0,
        "unmatched": prepared.unmatched,
        "updated": 0,
        "article_updated": 0,
        "duplicates": 0,
        "conflicts": 0,
    }
    details = _callback_details(event)
    outcomes: list[dict[str, Any]] = []
    outcome_reasons: list[str] = []
    for ref in prepared.refs:
        _apply_one_attempt_callback(
            prepared,
            ref,
            target_state=target_state,
            deploy_url=deploy_url,
            details=details,
            counts=counts,
            outcomes=outcomes,
            reasons=outcome_reasons,
        )

    return _attempt_callback_result(
        event,
        target_state,
        deploy_url,
        counts,
        outcomes,
        outcome_reasons,
    )


def _track_check_pass_outcome(
    counts: dict[str, int],
    outcomes: list[dict[str, Any]],
    reasons: list[str],
    ref: Any,
    outcome: Any,
) -> None:
    counts["matched"] += int(outcome.matched)
    counts["unmatched"] += int(not outcome.matched)
    counts["recorded"] += int(outcome.recorded)
    counts["duplicates"] += int(outcome.reason == "already_recorded")
    counts["conflicts"] += int(
        outcome.matched
        and not outcome.recorded
        and outcome.reason != "already_recorded"
    )
    reasons.append(outcome.reason)
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


def _record_check_passed_events(
    event: ValidationResultEvent, db: DatabaseManager
) -> dict[str, Any]:
    if not event.publication_ids:
        return _no_publication_ids_result(include_article_updated=False)
    prepared = _prepare_attempt_callback(event, db, "record_correlated_check_passed")
    if isinstance(prepared, dict):
        return prepared

    counts = {
        "matched": 0,
        "unmatched": prepared.unmatched,
        "recorded": 0,
        "duplicates": 0,
        "conflicts": 0,
    }
    outcomes: list[dict[str, Any]] = []
    outcome_reasons: list[str] = []
    details = _callback_details(event)
    for ref in prepared.refs:
        outcome = prepared.apply(
            refinery_id=ref.refinery_id,
            pull_request_number=ref.pull_request_number,
            content_sha256=ref.content_sha256,
            callback_details=details,
        )
        _track_check_pass_outcome(counts, outcomes, outcome_reasons, ref, outcome)

    needs_attention = bool(counts["unmatched"] or counts["conflicts"])
    _log_check_pass_outcome(event, counts, needs_attention)
    action = _check_pass_callback_action(counts, needs_attention)
    return {
        "action": action,
        "updated": 0,
        "recorded": counts["recorded"],
        "matched": counts["matched"],
        "unmatched": counts["unmatched"],
        "duplicates": counts["duplicates"],
        "conflicts": counts["conflicts"],
        "needs_attention": needs_attention,
        "retryable": _retryable_callback(outcome_reasons),
        "outcomes": outcomes,
        "reason": "validation_passed",
    }


def _log_check_pass_outcome(
    event: ValidationResultEvent, counts: dict[str, int], needs_attention: bool
) -> None:
    if needs_attention:
        logger.warning(
            "Validation pass callback has unmatched/terminal attempts "
            "(unmatched={}, conflicts={}, run_url={}).",
            counts["unmatched"],
            counts["conflicts"],
            event.run_url,
        )


def _check_pass_callback_action(counts: dict[str, int], needs_attention: bool) -> str:
    if counts["recorded"] and needs_attention:
        return "partial"
    if counts["unmatched"]:
        return "unmatched"
    if counts["conflicts"]:
        return "conflict"
    return "noop"


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
