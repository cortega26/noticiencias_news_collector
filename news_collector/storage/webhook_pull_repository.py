"""Durable staging and cursor state for the ADR-0011 hosted inbox puller."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from sqlalchemy import and_, func, null, or_
from sqlalchemy.exc import IntegrityError

from .models import WebhookPullCursor as _WebhookPullCursorModel
from .models import WebhookPullReceipt as _WebhookPullReceiptModel


class CursorConflict(RuntimeError):
    """Another puller changed the high-water mark while this page was fetched."""


@dataclass(frozen=True)
class WebhookPullReceiptView:
    id: int
    endpoint_key: str
    remote_id: int
    delivery_key: Optional[str]
    event_type: Optional[str]
    payload: Optional[Dict[str, Any]]
    status: str
    attempts: int
    error: Optional[str]
    last_attempt_at: Optional[datetime]
    lease_until: Optional[float]
    lease_token: Optional[str]
    received_at: datetime
    processed_at: Optional[datetime]


def _to_view(row: _WebhookPullReceiptModel) -> WebhookPullReceiptView:
    return WebhookPullReceiptView(
        id=row.id,
        endpoint_key=row.endpoint_key,
        remote_id=row.remote_id,
        delivery_key=row.delivery_key,
        event_type=row.event_type,
        payload=row.payload,
        status=row.status,
        attempts=row.attempts,
        error=row.error,
        last_attempt_at=row.last_attempt_at,
        lease_until=row.lease_until,
        lease_token=row.lease_token,
        received_at=row.received_at,
        processed_at=row.processed_at,
    )


def _receipt_from_remote_row(
    endpoint_key: str, row: Dict[str, Any]
) -> _WebhookPullReceiptModel:
    payload = row.get("payload")
    delivery_key = row.get("delivery_key")
    event_type = row.get("event_type")
    return _WebhookPullReceiptModel(
        endpoint_key=endpoint_key,
        remote_id=row["id"],
        delivery_key=delivery_key if isinstance(delivery_key, str) else None,
        event_type=event_type if isinstance(event_type, str) else None,
        # Preserve the complete row so malformed events remain retryable.
        payload=dict(row) if isinstance(payload, dict) else row,
        status="received",
        attempts=0,
    )


class WebhookPullReceiptRepository:
    """Stage remote rows before advancing the cursor or applying callbacks.

    A page insert and its cursor advance share one database transaction. Each
    pending row is claimed with a lease, so a crash makes it retryable and two
    pullers do not normally apply the same staged row concurrently.
    """

    def __init__(self, db_manager: Any) -> None:
        self._db = db_manager

    @contextmanager
    def _session(self):
        with self._db.get_session() as session:
            yield session

    def get_cursor(self, endpoint_key: str) -> Optional[int]:
        with self._session() as session:
            cursor = (
                session.query(_WebhookPullCursorModel)
                .filter_by(endpoint_key=endpoint_key)
                .first()
            )
            return cursor.after_id if cursor is not None else None

    def stage_page(
        self,
        endpoint_key: str,
        *,
        expected_after_id: Optional[int],
        rows: list[Dict[str, Any]],
    ) -> int:
        """Persist a complete page before committing its remote high-water ID."""
        if not rows:
            return 0

        try:
            with self._session() as session:
                cursor = (
                    session.query(_WebhookPullCursorModel)
                    .filter_by(endpoint_key=endpoint_key)
                    .with_for_update()
                    .first()
                )
                current_after_id = cursor.after_id if cursor is not None else None
                if current_after_id != expected_after_id:
                    raise CursorConflict("hosted receipt cursor changed concurrently")

                session.add_all(
                    _receipt_from_remote_row(endpoint_key, row) for row in rows
                )
                next_after_id = rows[-1]["id"]
                self._advance_cursor(session, cursor, endpoint_key, next_after_id)
                session.flush()
                return len(rows)
        except IntegrityError as exc:
            raise CursorConflict(
                "hosted receipt page conflicted with another puller"
            ) from exc

    @staticmethod
    def _advance_cursor(session, cursor, endpoint_key: str, next_after_id: int) -> None:
        if cursor is None:
            session.add(
                _WebhookPullCursorModel(
                    endpoint_key=endpoint_key,
                    after_id=next_after_id,
                )
            )
            return
        cursor.after_id = next_after_id
        cursor.updated_at = datetime.now(timezone.utc)

    @staticmethod
    def _oldest_pending(
        session, endpoint_key: str
    ) -> Optional[_WebhookPullReceiptModel]:
        return (
            session.query(_WebhookPullReceiptModel)
            .filter(
                _WebhookPullReceiptModel.endpoint_key == endpoint_key,
                _WebhookPullReceiptModel.status != "processed",
            )
            .order_by(_WebhookPullReceiptModel.remote_id.asc())
            .first()
        )

    @staticmethod
    def _is_claim_eligible(row, retry_only: bool, now_epoch: float) -> bool:
        if row.status == "received":
            return row.attempts > 0 if retry_only else row.attempts == 0
        if retry_only and row.status == "failed":
            return True
        if not retry_only or row.status != "processing":
            return False
        return row.lease_until is None or row.lease_until <= now_epoch

    @staticmethod
    def _claimable_filter(retry_only: bool, now_epoch: float):
        if not retry_only:
            return and_(
                _WebhookPullReceiptModel.status == "received",
                _WebhookPullReceiptModel.attempts == 0,
            )
        expired_lease = and_(
            _WebhookPullReceiptModel.status == "processing",
            or_(
                _WebhookPullReceiptModel.lease_until.is_(None),
                _WebhookPullReceiptModel.lease_until <= now_epoch,
            ),
        )
        return or_(
            _WebhookPullReceiptModel.status == "failed",
            and_(
                _WebhookPullReceiptModel.status == "received",
                _WebhookPullReceiptModel.attempts > 0,
            ),
            expired_lease,
        )

    @staticmethod
    def _leased_view(row, now: datetime, lease_until: float, lease_token: str):
        return WebhookPullReceiptView(
            id=row.id,
            endpoint_key=row.endpoint_key,
            remote_id=row.remote_id,
            delivery_key=row.delivery_key,
            event_type=row.event_type,
            payload=row.payload,
            status="processing",
            attempts=row.attempts + 1,
            error=None,
            last_attempt_at=now,
            lease_until=lease_until,
            lease_token=lease_token,
            received_at=row.received_at,
            processed_at=row.processed_at,
        )

    def claim_pending(
        self,
        endpoint_key: str,
        *,
        limit: int,
        lease_seconds: int,
        retry_only: bool,
    ) -> list[WebhookPullReceiptView]:
        """Lease the oldest pending row, preserving order across concurrent pulls."""
        if limit <= 0:
            return []

        now = datetime.now(timezone.utc)
        now_epoch = now.timestamp()
        lease_until = (now + timedelta(seconds=lease_seconds)).timestamp()
        with self._session() as session:
            row = self._oldest_pending(session, endpoint_key)
            if row is None or not self._is_claim_eligible(row, retry_only, now_epoch):
                return []

            lease_token = uuid4().hex
            changed = (
                session.query(_WebhookPullReceiptModel)
                .filter(
                    _WebhookPullReceiptModel.id == row.id,
                    self._claimable_filter(retry_only, now_epoch),
                )
                .update(
                    {
                        "status": "processing",
                        "attempts": _WebhookPullReceiptModel.attempts + 1,
                        "last_attempt_at": now,
                        "lease_until": lease_until,
                        "lease_token": lease_token,
                        "error": None,
                    },
                    synchronize_session=False,
                )
            )
            if changed != 1:
                return []
            return [self._leased_view(row, now, lease_until, lease_token)]

    def mark_processed(self, receipt_id: int, lease_token: str) -> bool:
        """Acknowledge local application and discard the staged raw payload."""
        with self._session() as session:
            changed = (
                session.query(_WebhookPullReceiptModel)
                .filter_by(id=receipt_id, status="processing", lease_token=lease_token)
                .update(
                    {
                        "status": "processed",
                        "payload": None,
                        "error": None,
                        "lease_until": None,
                        "lease_token": null(),
                        "processed_at": datetime.now(timezone.utc),
                    },
                    synchronize_session=False,
                )
            )
            return bool(changed == 1)

    def mark_failed(self, receipt_id: int, lease_token: str, error: str) -> bool:
        """Keep the raw event visible and retryable after a failed application."""
        with self._session() as session:
            changed = (
                session.query(_WebhookPullReceiptModel)
                .filter_by(id=receipt_id, status="processing", lease_token=lease_token)
                .update(
                    {
                        "status": "failed",
                        "error": error[:500],
                        "lease_until": None,
                        "lease_token": null(),
                    },
                    synchronize_session=False,
                )
            )
            return bool(changed == 1)

    def count_pending(self, endpoint_key: str) -> int:
        with self._session() as session:
            return int(
                session.query(func.count(_WebhookPullReceiptModel.id))
                .filter(
                    _WebhookPullReceiptModel.endpoint_key == endpoint_key,
                    _WebhookPullReceiptModel.status != "processed",
                )
                .scalar()
                or 0
            )

    def get_receipt(
        self, endpoint_key: str, remote_id: int
    ) -> Optional[WebhookPullReceiptView]:
        with self._session() as session:
            row = (
                session.query(_WebhookPullReceiptModel)
                .filter_by(endpoint_key=endpoint_key, remote_id=remote_id)
                .first()
            )
            return _to_view(row) if row is not None else None
