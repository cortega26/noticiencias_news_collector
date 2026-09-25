"""Webhook receipt repository — durable, idempotent frontend callback log
(Plan 060 / Phase 5a).

One row per distinct delivery (`delivery_key`), persisted *before* the handler
processes it. The serving endpoint answers 202 only after this row exists, so a
crash or a lost response no longer discards the callback. `status` traces the
delivery lifecycle (`received → processed|failed`), `attempts` counts processing
attempts, and `result`/`error` keep the outcome operator-visible.

Return types are plain frozen dataclasses (same convention as
`LifecycleRepository`): backend-internal lifecycle records with no cross-repo
relevance, so they do not belong in `contracts/`.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from news_collector.utils.logger import get_logger

from .models import WebhookReceipt as _WebhookReceiptModel

logger = get_logger().create_module_logger(__name__)


@dataclass(frozen=True)
class WebhookReceiptView:
    """Read projection of one ``webhook_receipts`` row."""

    id: int
    delivery_key: str
    event_type: str
    payload: Dict[str, Any]
    status: str
    attempts: int
    result: Optional[Dict[str, Any]]
    error: Optional[str]
    received_at: datetime
    processed_at: Optional[datetime]


def _to_view(row: _WebhookReceiptModel) -> WebhookReceiptView:
    return WebhookReceiptView(
        id=row.id,
        delivery_key=row.delivery_key,
        event_type=row.event_type,
        payload=row.payload,
        status=row.status,
        attempts=row.attempts,
        result=row.result,
        error=row.error,
        received_at=row.received_at,
        processed_at=row.processed_at,
    )


class WebhookReceiptRepository:
    """Typed access to the durable webhook-delivery receipts.

    Receives a DatabaseManager (or any object with ``get_session()``) as its
    session provider, matching the other focused repositories.
    """

    def __init__(self, db_manager: Any) -> None:
        self._db = db_manager

    @contextmanager
    def _session(self):
        with self._db.get_session() as session:
            yield session

    def record_receipt(
        self,
        *,
        delivery_key: str,
        event_type: str,
        payload: Dict[str, Any],
    ) -> tuple[WebhookReceiptView, bool]:
        """Insert the receipt for one delivery.

        Returns ``(view, True)`` for a first delivery and ``(stored_view,
        False)`` when the key already exists (a replay) — the stored row wins,
        no mutation. A concurrent insert that loses the unique-index race falls
        back to the stored row instead of raising.
        """
        try:
            with self._session() as session:
                existing = self._get_row(session, delivery_key)
                if existing is not None:
                    return _to_view(existing), False
                row = _WebhookReceiptModel(
                    delivery_key=delivery_key,
                    event_type=event_type,
                    payload=payload,
                    status="received",
                    attempts=0,
                )
                session.add(row)
                session.flush()
                return _to_view(row), True
        except IntegrityError:
            logger.info(
                "Concurrent webhook receipt insert for key {}; using the stored row.",
                delivery_key,
            )
            stored = self.get_receipt(delivery_key)
            if stored is None:
                raise
            return stored, False

    def mark_processing(self, delivery_key: str) -> bool:
        """Increment the processing-attempt counter. False when key is unknown."""
        with self._session() as session:
            row = self._get_row(session, delivery_key)
            if row is None:
                return False
            row.attempts = (row.attempts or 0) + 1
            return True

    def mark_processed(
        self, delivery_key: str, result: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Record a successful processing outcome. False when key is unknown."""
        with self._session() as session:
            row = self._get_row(session, delivery_key)
            if row is None:
                return False
            row.status = "processed"
            row.result = result
            row.error = None
            row.processed_at = datetime.now(timezone.utc)
            return True

    def mark_failed(self, delivery_key: str, error: str) -> bool:
        """Record a processing failure and keep it operator-visible.

        The delivery stays retryable: a replay of the same key reprocesses it.
        False when key is unknown.
        """
        with self._session() as session:
            row = self._get_row(session, delivery_key)
            if row is None:
                return False
            row.status = "failed"
            row.error = error
            row.processed_at = datetime.now(timezone.utc)
            return True

    def get_receipt(self, delivery_key: str) -> Optional[WebhookReceiptView]:
        with self._session() as session:
            row = self._get_row(session, delivery_key)
            return _to_view(row) if row is not None else None

    @staticmethod
    def _get_row(session: Session, delivery_key: str) -> Optional[_WebhookReceiptModel]:
        return (
            session.query(_WebhookReceiptModel)
            .filter(_WebhookReceiptModel.delivery_key == delivery_key)
            .first()
        )
