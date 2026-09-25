"""
Webhook event processing logic.

Handles frontend CI callbacks by updating article publication state in the
database. Plan 060 / Phase 5a: handling is receipt-first — the delivery is
persisted (``db.webhook_receipts``) before any transition, a replay of a
processed delivery returns the stored result without reapplying transitions,
and a processing exception leaves a ``failed`` receipt (with its error) instead
of vanishing behind the always-202 response.

Plan 021: matching is keyed by ``event.publication_ids`` (stable
refinery_ids persisted at PR-creation time), not branch equality —
branch/commit_sha remain in the event as audit context only. A
callback with no ``publication_ids`` cannot safely mutate any article
(there is nothing to key the mutation to) and is a no-op, logged as a
warning rather than silently guessed at via branch matching.

Plan 060 / Phase 5b: the callback *effects* (state transitions and
``publication_events`` audit rows) live in
``news_collector.logic.workflows.publication_callbacks``; the
``process_*`` functions here are thin delegates kept as the dispatch seam
the receipt handler and its tests already use.
"""

from __future__ import annotations

from typing import Any, Dict

from news_collector.contracts.webhook import (
    AnyWebhookEvent,
    PublishCompleteEvent,
    ValidationResultEvent,
    compute_delivery_key,
)
from news_collector.logic.workflows.publication_callbacks import (
    apply_publish_complete,
    apply_validation_result,
)
from news_collector.storage.database import DatabaseManager
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)


def handle_webhook_event(
    event: AnyWebhookEvent,
    db: DatabaseManager,
) -> Dict[str, Any]:
    """Persist one delivery, then process it at most once per delivery key.

    The returned dict is the JSON body the endpoint sends (always 202 unless
    payload validation failed before this point). A duplicate of an already
    ``processed`` delivery returns its stored result; a ``received`` (crashed
    mid-flight) or ``failed`` receipt is reprocessed — the underlying
    transitions are state-filtered, so replay is safe.
    """
    receipts = getattr(db, "webhook_receipts", None)
    if receipts is None:
        # Backward-compatible fallback for managers predating the receipts
        # repository (custom fakes): process best-effort without a receipt.
        return _process_without_receipt(event, db)

    delivery_key = compute_delivery_key(event)
    receipt, created = receipts.record_receipt(
        delivery_key=delivery_key,
        event_type=event.event,
        payload=event.model_dump(mode="json", by_alias=True),
    )
    if not created and receipt.status == "processed":
        logger.info(
            "Duplicate webhook delivery {} ({}) — returning stored result.",
            delivery_key,
            event.event,
        )
        return {
            "accepted": True,
            "event": event.event,
            "duplicate": True,
            "result": receipt.result or {},
        }

    receipts.mark_processing(delivery_key)
    try:
        result = _dispatch(event, db)
    except Exception as exc:
        logger.error(
            "Webhook processing error (event={}, delivery_key={}): {}",
            event.event,
            delivery_key,
            exc,
            exc_info=True,
        )
        receipts.mark_failed(delivery_key, f"{type(exc).__name__}: {exc}")
        return {"accepted": True, "event": event.event, "processed": False}

    receipts.mark_processed(delivery_key, result)
    return {"accepted": True, "event": event.event, "result": result}


def _dispatch(event: AnyWebhookEvent, db: DatabaseManager) -> Dict[str, Any]:
    if isinstance(event, ValidationResultEvent):
        return process_validation_result(event, db)
    if isinstance(event, PublishCompleteEvent):
        return process_publish_complete(event, db)
    return {"action": "noop", "reason": "unhandled_event_type"}


def _process_without_receipt(
    event: AnyWebhookEvent, db: DatabaseManager
) -> Dict[str, Any]:
    try:
        result = _dispatch(event, db)
    except Exception as exc:
        logger.error(
            "Webhook processing error (event={}): {}",
            event.event,
            exc,
            exc_info=True,
        )
        return {"accepted": True, "event": event.event, "processed": False}
    return {"accepted": True, "event": event.event, "result": result}


def process_validation_result(
    event: ValidationResultEvent,
    db: DatabaseManager,
) -> Dict[str, Any]:
    """Thin delegate to the workflow-owned callback effect (plan 5b).

    Kept under this module's name so ``_dispatch`` and the existing
    direct-call / ``patch(...)`` test seams stay exactly where they were;
    the implementation lives in
    :func:`news_collector.logic.workflows.publication_callbacks.apply_validation_result`.
    """
    return apply_validation_result(event, db)


def process_publish_complete(
    event: PublishCompleteEvent,
    db: DatabaseManager,
) -> Dict[str, Any]:
    """Thin delegate to the workflow-owned callback effect (plan 5b); see
    :func:`process_validation_result` for why the name stays here."""
    return apply_publish_complete(event, db)
