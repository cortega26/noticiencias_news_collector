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
from urllib.parse import urlsplit

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
from news_collector.utils.logger import get_logger  # noqa: E402

logger = get_logger().create_module_logger(__name__)

RECEIPTS_PATH = "/v1/admin/webhook/receipts"
DEFAULT_LIMIT = 200
DEFAULT_MAX_RECEIPTS = 2000
TIMEOUT_SECONDS = 30

#: Signature of the page fetcher (injectable in tests).
PageFetcher = Callable[..., List[Dict[str, Any]]]


@dataclass
class PullSummary:
    """Outcome of one pull pass (``replayed`` = applied or would-apply)."""

    fetched: int = 0
    replayed: int = 0
    duplicates: int = 0
    failed: int = 0
    malformed: int = 0
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
    try:
        response = requests.get(
            endpoint,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise PullError(f"could not reach {endpoint}: {exc}") from exc
    if response.status_code in (401, 403):
        raise PullError(
            f"admin authentication rejected by {endpoint} "
            f"(status {response.status_code}) — check ADMIN_API_KEY"
        )
    if response.status_code != 200:
        raise PullError(
            f"unexpected status {response.status_code} from {endpoint}: "
            f"{response.text[:200]}"
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise PullError(f"non-JSON response from {endpoint}") from exc
    receipts = body.get("receipts") if isinstance(body, dict) else None
    if not isinstance(receipts, list):
        raise PullError(f"response from {endpoint} has no receipts list")
    return [row for row in receipts if isinstance(row, dict)]


def _replay_receipt(
    row: Dict[str, Any], db: DatabaseManager, summary: PullSummary
) -> None:
    """Apply one receipt payload through the real webhook handler."""
    receipt_id = row.get("id")
    try:
        event = parse_webhook_payload(row.get("payload"))
    except Exception as exc:  # malformed payload: report, never guess
        summary.malformed += 1
        logger.warning(
            "Skipping malformed receipt id={} delivery_key={}: {}",
            receipt_id,
            row.get("delivery_key"),
            exc,
        )
        return

    if summary.dry_run:
        existing = db.webhook_receipts.get_receipt(compute_delivery_key(event))
        if existing is not None and existing.status == "processed":
            summary.duplicates += 1
        else:
            summary.replayed += 1
        return

    result = handle_webhook_event(event, db)
    if result.get("duplicate"):
        summary.duplicates += 1
    elif result.get("processed", True) is False or "result" not in result:
        summary.failed += 1
    else:
        summary.replayed += 1


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
    """Page the hosted inbox forward and replay every delivery exactly once."""
    page_fetcher = fetcher or fetch_page
    summary = PullSummary(dry_run=dry_run)
    after_id: Optional[int] = None
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
        for row in rows:
            summary.fetched += 1
            after_id = row.get("id", after_id)
            _replay_receipt(row, db, summary)
        if len(rows) < page_limit:
            break
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
    print(f"[pull-webhooks] replayed={summary.replayed}")
    print(f"[pull-webhooks] duplicates={summary.duplicates}")
    print(f"[pull-webhooks] failed={summary.failed}")
    print(f"[pull-webhooks] malformed={summary.malformed}")
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
