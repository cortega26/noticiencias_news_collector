#!/usr/bin/env python3
"""Pull durable frontend callbacks from the hosted serving inbox (ADR-0011).

The hosted serving instance (`api.noticiencias.com`) receives the frontend CI
webhooks and persists each delivery as a `webhook_receipts` row before
processing it. Its database is *not* the system of record — publication runs
execute against the local DB — so the delivery must be replayed here through
the same handler the serving endpoint uses (`handle_webhook_event`):
receipt-first and idempotent by delivery key, so pages can be re-pulled
safely and a second pass is a no-op.

Endpoint resolution (first hit wins):
    1. ``--endpoint``
    2. ``BACKEND_ADMIN_URL`` + ``/v1/admin/webhook/receipts``
    3. origin of ``BACKEND_WEBHOOK_URL`` + ``/v1/admin/webhook/receipts``
Token resolution: ``--token`` → ``ADMIN_API_KEY``.

Usage:
    python scripts/ops/pull_webhook_receipts.py [--endpoint URL] [--token T]
        [--limit 200] [--max-receipts 2000] [--dry-run]

Exit codes: 0 on a completed pass (malformed payloads are a report, matching
`reconcile_publication_attempts.py`), 1 when the endpoint/token cannot be
resolved or the fetch fails — a timer can act on it.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from news_collector.contracts.webhook import (  # noqa: E402
    compute_delivery_key,
    parse_webhook_payload,
)
from news_collector.serving.webhook_handler import handle_webhook_event  # noqa: E402
from news_collector.storage.database import DatabaseManager  # noqa: E402
from news_collector.storage.webhook_pull_repository import (  # noqa: E402
    CursorConflict,
    WebhookPullReceiptView,
)
from news_collector.utils.logger import get_logger  # noqa: E402

logger = get_logger().create_module_logger(__name__)

RECEIPTS_PATH = "/v1/admin/webhook/receipts"
DEFAULT_LIMIT = 200
DEFAULT_MAX_RECEIPTS = 2000
DEFAULT_LEASE_SECONDS = 600
TIMEOUT_SECONDS = 30

#: Signature of the page fetcher (injectable in tests).
PageFetcher = Callable[..., List[Dict[str, Any]]]


@dataclass
class PullSummary:
    """Counts distinguish fetched, durably staged, applied, and pending work."""

    fetched: int = 0
    staged: int = 0
    attempted: int = 0
    replayed: int = 0
    duplicates: int = 0
    failed: int = 0
    malformed: int = 0
    business_attention: int = 0
    pending: int = 0
    truncated: bool = False
    dry_run: bool = False


class PullError(RuntimeError):
    """Unrecoverable pull failure (bad credentials, transport, bad response)."""


def resolve_endpoint(
    explicit: Optional[str] = None,
    admin_url: Optional[str] = None,
    webhook_url: Optional[str] = None,
) -> Optional[str]:
    """Resolve the receipts endpoint from explicit value or environment URLs.

    ``BACKEND_WEBHOOK_URL`` points at the callback route itself; only its
    origin is reused, because the admin surface lives under a different path.
    """
    if explicit:
        return explicit
    if admin_url:
        return admin_url.rstrip("/") + RECEIPTS_PATH
    if webhook_url:
        parts = urlsplit(webhook_url)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}{RECEIPTS_PATH}"
    return None


def _request_page(
    endpoint: str, token: str, params: Dict[str, Any]
) -> "requests.Response":
    """GET one page, converting transport failures into :class:`PullError`."""
    try:
        return requests.get(
            endpoint,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise PullError(
            f"could not reach {_safe_endpoint(endpoint)} "
            f"(error_type={type(exc).__name__})"
        ) from exc


def _safe_endpoint(endpoint: str) -> str:
    """Return an origin/path suitable for diagnostics and durable identity.

    Userinfo, query parameters, and fragments can contain credentials. They
    are neither part of the receipt inbox identity nor safe to log.
    """
    parts = urlsplit(endpoint)
    hostname = parts.hostname
    if not parts.scheme or not hostname:
        return "<invalid-endpoint>"
    try:
        port = parts.port
    except ValueError:
        return "<invalid-endpoint>"
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = f"{hostname.lower()}:{port}" if port is not None else hostname.lower()
    return urlunsplit(
        (
            parts.scheme.lower(),
            netloc,
            parts.path.rstrip("/"),
            "",
            "",
        )
    )


def _decode_receipts(
    response: "requests.Response", endpoint: str
) -> List[Dict[str, Any]]:
    """Validate the response envelope and return its receipt dicts."""
    safe_endpoint = _safe_endpoint(endpoint)
    if response.status_code in (401, 403):
        raise PullError(
            f"admin authentication rejected by {safe_endpoint} "
            f"(status {response.status_code}) — check ADMIN_API_KEY"
        )
    if response.status_code != 200:
        raise PullError(
            f"unexpected status {response.status_code} from {safe_endpoint}"
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise PullError(f"non-JSON response from {safe_endpoint}") from exc
    receipts = body.get("receipts") if isinstance(body, dict) else None
    if not isinstance(receipts, list):
        raise PullError(f"response from {safe_endpoint} has no receipts list")
    if any(not isinstance(row, dict) for row in receipts):
        raise PullError(f"response from {safe_endpoint} contains a non-object receipt")
    return receipts


def fetch_page(
    *,
    endpoint: str,
    token: str,
    after_id: Optional[int],
    limit: int,
) -> List[Dict[str, Any]]:
    """Fetch one page of receipts from the hosted inbox."""
    params: Dict[str, Any] = {"limit": limit}
    if after_id is not None:
        params["after_id"] = after_id
    return _decode_receipts(_request_page(endpoint, token, params), endpoint)


def _replay_receipt(
    row: Dict[str, Any], db: DatabaseManager, summary: PullSummary
) -> tuple[bool, str | None]:
    """Apply one receipt payload; return whether it reached a safe outcome."""
    try:
        event = parse_webhook_payload(row.get("payload"))
    except Exception as exc:  # malformed payload: report, never guess
        summary.malformed += 1
        summary.failed += 1
        logger.warning(
            "Malformed hosted receipt retained for retry (error_type={})",
            type(exc).__name__,
        )
        return False, f"malformed:{type(exc).__name__}"

    if summary.dry_run:
        existing = db.webhook_receipts.get_receipt(compute_delivery_key(event))
        if existing is not None and existing.status == "processed":
            summary.duplicates += 1
        else:
            summary.replayed += 1
        return True, None

    try:
        result = handle_webhook_event(event, db, retry_business_attention=True)
    except Exception as exc:  # preserve the failure and retry the staged row
        summary.failed += 1
        logger.warning(
            "Hosted receipt handler raised (error_type={})", type(exc).__name__
        )
        return False, f"handler_exception:{type(exc).__name__}"

    if not isinstance(result, dict):
        summary.failed += 1
        return False, "handler_returned_invalid_result"
    business_result = result.get("result")
    if isinstance(business_result, dict) and business_result.get("needs_attention"):
        summary.business_attention += 1
        if business_result.get("retryable"):
            summary.failed += 1
            reason = str(business_result.get("reason", "correlation_pending"))[:120]
            return False, f"business_attention_retryable:{reason}"
    if result.get("duplicate"):
        summary.duplicates += 1
    elif result.get("processed", True) is False or "result" not in result:
        summary.failed += 1
        return False, "handler_did_not_process"
    else:
        summary.replayed += 1
    return True, None


def _endpoint_key(endpoint: str) -> str:
    """Stable inbox identity without query parameters or URL fragments."""
    safe_endpoint = _safe_endpoint(endpoint)
    if safe_endpoint == "<invalid-endpoint>":
        raise PullError("receipts endpoint must be an absolute URL")
    return safe_endpoint


def _validate_page(rows: List[Dict[str, Any]], after_id: Optional[int]) -> int:
    """Require strict, ascending hosted IDs before persisting a page cursor."""
    previous = after_id
    for row in rows:
        receipt_id = row.get("id")
        if isinstance(receipt_id, bool) or not isinstance(receipt_id, int):
            raise PullError("hosted receipt page has a missing or invalid id")
        if receipt_id < 1 or (previous is not None and receipt_id <= previous):
            raise PullError("hosted receipt page is not strictly ordered by id")
        previous = receipt_id
    if previous is None:
        raise PullError("hosted receipt page is empty")
    return previous


def _mark_malformed_claim(
    receipt: WebhookPullReceiptView,
    repo,
    summary: PullSummary,
) -> bool:
    summary.failed += 1
    summary.malformed += 1
    settled = repo.mark_failed(
        receipt.id,
        receipt.lease_token or "",
        "malformed:staged_payload_not_object",
    )
    if not settled:
        logger.warning("Could not settle a leased hosted receipt row")
        summary.failed += 1
    return False


def _settle_claimed(
    receipt: WebhookPullReceiptView,
    repo,
    summary: PullSummary,
    applied: bool,
    error: str | None,
) -> bool:
    if applied:
        settled = repo.mark_processed(receipt.id, receipt.lease_token or "")
    else:
        settled = repo.mark_failed(
            receipt.id,
            receipt.lease_token or "",
            error or "handler_did_not_process",
        )
    if settled:
        return True
    summary.failed += 1
    logger.warning("Could not settle a leased hosted receipt row")
    return False


def _apply_one_claimed(
    receipt: WebhookPullReceiptView,
    db: DatabaseManager,
    summary: PullSummary,
) -> bool:
    """Apply and settle one leased row; keep failures retryable."""
    raw_row = receipt.payload
    if not isinstance(raw_row, dict):
        return _mark_malformed_claim(receipt, db.webhook_pull_receipts, summary)

    applied, error = _replay_receipt(raw_row, db, summary)
    if not _settle_claimed(
        receipt,
        db.webhook_pull_receipts,
        summary,
        applied,
        error,
    ):
        return False
    return applied


def _apply_claimed(
    receipts: List[WebhookPullReceiptView],
    db: DatabaseManager,
    summary: PullSummary,
) -> bool:
    """Apply leased rows in order; stop at the first unacknowledged event."""
    for receipt in receipts:
        summary.attempted += 1
        if not _apply_one_claimed(receipt, db, summary):
            return False
    return True


def _drain_pending(
    db: DatabaseManager,
    endpoint_key: str,
    summary: PullSummary,
    *,
    max_attempts: int,
) -> None:
    """Retry the oldest event first and never pass an unacknowledged ID."""
    repo = db.webhook_pull_receipts
    for _ in range(max_attempts):
        batch = repo.claim_pending(
            endpoint_key,
            limit=1,
            lease_seconds=DEFAULT_LEASE_SECONDS,
            retry_only=True,
        )
        if not batch:
            batch = repo.claim_pending(
                endpoint_key,
                limit=1,
                lease_seconds=DEFAULT_LEASE_SECONDS,
                retry_only=False,
            )
        if not batch or not _apply_claimed(batch, db, summary):
            break


def pull_receipts(
    db: DatabaseManager,
    *,
    endpoint: str,
    token: str,
    limit: int = DEFAULT_LIMIT,
    max_receipts: int = DEFAULT_MAX_RECEIPTS,
    dry_run: bool = False,
    fetcher: Optional[PageFetcher] = None,
) -> PullSummary:
    """Stage hosted pages durably, then apply and retry staged deliveries."""
    if limit < 1:
        raise PullError("page limit must be at least 1")
    if max_receipts < 0:
        raise PullError("max receipts must be zero or greater")

    page_fetcher = fetcher or fetch_page
    summary = PullSummary(dry_run=dry_run)
    endpoint_key = _endpoint_key(endpoint)
    repo = db.webhook_pull_receipts
    after_id = repo.get_cursor(endpoint_key)

    while summary.fetched < max_receipts:
        page_limit = min(limit, max_receipts - summary.fetched)
        rows = page_fetcher(
            endpoint=endpoint,
            token=token,
            after_id=after_id,
            limit=page_limit,
        )
        if not rows:
            break
        if len(rows) > page_limit:
            raise PullError("hosted receipt page exceeded the requested limit")
        next_after_id = _validate_page(rows, after_id)
        summary.fetched += len(rows)
        if dry_run:
            for row in rows:
                _replay_receipt(row, db, summary)
        else:
            try:
                summary.staged += repo.stage_page(
                    endpoint_key,
                    expected_after_id=after_id,
                    rows=rows,
                )
            except CursorConflict as exc:
                raise PullError(
                    "another puller advanced this inbox; rerun to resume"
                ) from exc
        after_id = next_after_id

        if summary.fetched >= max_receipts:
            summary.truncated = len(rows) == page_limit
            break
        if len(rows) < page_limit:
            break

    if dry_run:
        return summary

    _drain_pending(
        db,
        endpoint_key,
        summary,
        max_attempts=max_receipts,
    )
    summary.pending = repo.count_pending(endpoint_key)
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Pull frontend callback receipts from the hosted serving inbox "
            "and replay them into the local database (ADR-0011). Idempotent "
            "by delivery key."
        )
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        help=(
            "Full receipts endpoint URL. Default: BACKEND_ADMIN_URL + "
            f"{RECEIPTS_PATH}, else the origin of BACKEND_WEBHOOK_URL + "
            f"{RECEIPTS_PATH}."
        ),
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Admin bearer token. Default: ADMIN_API_KEY.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Receipts per page (default: {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--max-receipts",
        type=int,
        default=DEFAULT_MAX_RECEIPTS,
        help=f"Safety cap per pass (default: {DEFAULT_MAX_RECEIPTS}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be replayed without writing anything.",
    )
    return parser


def _print_summary(summary: PullSummary) -> None:
    print(f"[pull-webhooks] fetched={summary.fetched}")
    print(f"[pull-webhooks] staged={summary.staged}")
    print(f"[pull-webhooks] attempted={summary.attempted}")
    print(f"[pull-webhooks] replayed={summary.replayed}")
    print(f"[pull-webhooks] duplicates={summary.duplicates}")
    print(f"[pull-webhooks] failed={summary.failed}")
    print(f"[pull-webhooks] malformed={summary.malformed}")
    print(f"[pull-webhooks] business_attention={summary.business_attention}")
    print(f"[pull-webhooks] pending={summary.pending}")
    print(f"[pull-webhooks] truncated={str(summary.truncated).lower()}")
    if summary.dry_run:
        print("[pull-webhooks] dry-run: no rows were written")


def main() -> int:
    args = _build_parser().parse_args()

    endpoint = resolve_endpoint(
        args.endpoint,
        os.environ.get("BACKEND_ADMIN_URL"),
        os.environ.get("BACKEND_WEBHOOK_URL"),
    )
    if not endpoint:
        print(
            "[pull-webhooks] no endpoint: set BACKEND_ADMIN_URL or "
            "BACKEND_WEBHOOK_URL, or pass --endpoint",
            file=sys.stderr,
        )
        return 1
    token = args.token or os.environ.get("ADMIN_API_KEY", "")
    if not token:
        print(
            "[pull-webhooks] no admin token: set ADMIN_API_KEY or pass --token",
            file=sys.stderr,
        )
        return 1

    db = DatabaseManager()
    try:
        try:
            summary = pull_receipts(
                db,
                endpoint=endpoint,
                token=token,
                limit=args.limit,
                max_receipts=args.max_receipts,
                dry_run=args.dry_run,
            )
        except PullError as exc:
            logger.error("Pull failed: {}", exc)
            print(f"[pull-webhooks] FAILED: {exc}", file=sys.stderr)
            return 1
    finally:
        db.close()

    _print_summary(summary)
    if summary.failed or summary.malformed:
        return 1
    if summary.pending or summary.truncated or summary.business_attention:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
