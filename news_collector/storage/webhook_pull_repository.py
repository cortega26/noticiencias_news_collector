"""Durable staging and cursor state for the ADR-0011 hosted inbox puller."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from sqlalchemy import and_, func, or_
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

                for row in rows:
                    payload = row.get("payload")
                    delivery_key = row.get("delivery_key")
                    event_type = row.get("event_type")
                    session.add(
                        _WebhookPullReceiptModel(
                            endpoint_key=endpoint_key,
                            remote_id=row["id"],
                            delivery_key=(
                                delivery_key if isinstance(delivery_key, str) else None
                            ),
                            event_type=(
                                event_type if isinstance(event_type, str) else None
                            ),
                            # Keep the complete remote row locally until it has
                            # been applied, so malformed events remain retryable.
                            payload=dict(row) if isinstance(payload, dict) else row,
                            status="received",
                            attempts=0,
                        )
                    )

                next_after_id = rows[-1]["id"]
                if cursor is None:
                    cursor = _WebhookPullCursorModel(
                        endpoint_key=endpoint_key,
                        after_id=next_after_id,
                    )
                    session.add(cursor)
                else:
                    cursor.after_id = next_after_id
                    cursor.updated_at = datetime.now(timezone.utc)
                session.flush()
                return len(rows)
        except IntegrityError as exc:
            raise CursorConflict(
                "hosted receipt page conflicted with another puller"
            ) from exc

    def claim_pending(
        self,
        endpoint_key: str,
        *,
        limit: int,
        lease_seconds: int,
        retry_only: bool,
    ) -> list[WebhookPullReceiptView]:
        """Lease only the oldest pending row so one failed event blocks later IDs."""
        if limit <= 0:
            return []

        now = datetime.now(timezone.utc)
        now_epoch = now.timestamp()
        lease_until = (now + timedelta(seconds=lease_seconds)).timestamp()
        claimed: list[WebhookPullReceiptView] = []
        with self._session() as session:
            # Ordered application matters for publication events. An active
            # lease on the oldest row blocks later rows until it settles or
            # expires, including when another puller is running concurrently.
            row = (
                session.query(_WebhookPullReceiptModel)
                .filter(
                    _WebhookPullReceiptModel.endpoint_key == endpoint_key,
                    _WebhookPullReceiptModel.status != "processed",
                )
                .order_by(_WebhookPullReceiptModel.remote_id.asc())
                .first()
            )
            if row is None:
                return []

            if row.status == "received" and row.attempts == 0:
                eligible = not retry_only
            elif row.status == "failed" or (
                row.status == "received" and row.attempts > 0
            ):
                eligible = retry_only
            elif row.status == "processing":
                eligible = retry_only and (
                    row.lease_until is None or row.lease_until <= now_epoch
                )
            else:
                eligible = False
            if not eligible:
                return []

            lease_token = uuid4().hex
            expired_lease = and_(
                _WebhookPullReceiptModel.status == "processing",
                or_(
                    _WebhookPullReceiptModel.lease_until.is_(None),
                    _WebhookPullReceiptModel.lease_until <= now_epoch,
                ),
            )
            claimable = (
                and_(
                    _WebhookPullReceiptModel.status == "received",
                    _WebhookPullReceiptModel.attempts == 0,
                )
                if not retry_only
                else or_(
                    _WebhookPullReceiptModel.status == "failed",
                    and_(
                        _WebhookPullReceiptModel.status == "received",
                        _WebhookPullReceiptModel.attempts > 0,
                    ),
                    expired_lease,
                )
            )
            changed = (
                session.query(_WebhookPullReceiptModel)
                .filter(
                    _WebhookPullReceiptModel.id == row.id,
                    claimable,
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
            if changed == 1:
                claimed.append(
                    WebhookPullReceiptView(
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
                )
        return claimed

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
                        "lease_token": None,
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
                        "lease_token": None,
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
