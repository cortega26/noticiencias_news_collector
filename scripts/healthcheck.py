"""Operational healthcheck for the News Collector stack."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import func, text
from sqlalchemy.exc import SQLAlchemyError

from src import get_database_manager, setup_logging
from src.storage.models import Article

DEFAULT_MAX_PENDING = int(os.getenv("HEALTHCHECK_MAX_PENDING", "250"))
DEFAULT_MAX_INGEST_LAG_MINUTES = int(os.getenv("HEALTHCHECK_MAX_INGEST_MINUTES", "180"))


@dataclass
class CheckResult:
    """Represents the outcome of a single health check."""

    name: str
    status: str
    details: Dict[str, Any]

    def prefix(self) -> str:
        if self.status == "ok":
            return "✅"
        if self.status == "warn":
            return "⚠️"
        return "❌"

    def summary(self) -> str:
        message = self.details.get("message")
        if message:
            return message

        if self.name == "database":
            return f"Database reachable via {self.details.get('engine', 'unknown')}"

        if self.name == "queue_backlog":
            pending = self.details.get("pending")
            threshold = self.details.get("threshold")
            return f"Pending articles: {pending} (threshold {threshold})"

        if self.name == "latest_ingest":
            latest = self.details.get("latest")
            lag = self.details.get("lag_minutes")
            threshold = self.details.get("threshold")
            if latest is None:
                return "No ingests recorded"
            if lag is None:
                return f"Last ingest at {latest}"
            return (
                f"Last ingest at {latest}; lag={lag:.1f} minutes "
                f"(threshold {threshold} minutes)"
            )

        return self.name.replace("_", " ").title()


def perform_healthcheck(
    *,
    db_manager=None,
    now: Optional[datetime] = None,
    max_pending: Optional[int] = None,
    max_ingest_lag_minutes: Optional[int] = None,
) -> Dict[str, Any]:
    """Run health validations for the collector stack."""

    db_manager = db_manager or get_database_manager()
    max_pending = DEFAULT_MAX_PENDING if max_pending is None else max_pending
    max_ingest_lag_minutes = (
        DEFAULT_MAX_INGEST_LAG_MINUTES
        if max_ingest_lag_minutes is None
        else max_ingest_lag_minutes
    )
    now = now or datetime.now(timezone.utc)

    checks: list[CheckResult] = []

    try:
        with db_manager.get_session() as session:
            session.execute(text("SELECT 1"))
            total_articles = session.query(func.count(Article.id)).scalar() or 0
            pending_articles = (
                session.query(func.count(Article.id))
                .filter(Article.processing_status == "pending")
                .scalar()
                or 0
            )
            latest_ingest: Optional[datetime] = session.query(
                func.max(Article.collected_date)
            ).scalar()
    except SQLAlchemyError as exc:  # pragma: no cover - defensive guard
        checks.append(
            CheckResult(
                name="database",
                status="fail",
                details={"message": f"Database query failed: {exc}"},
            )
        )
        return {"healthy": False, "checks": checks}
    except Exception as exc:
        checks.append(
            CheckResult(
                name="database",
                status="fail",
                details={"message": f"Database connection failed: {exc}"},
            )
        )
        return {"healthy": False, "checks": checks}

    checks.append(
        CheckResult(
            name="database",
            status="ok",
            details={"engine": db_manager.config.get("type", "unknown")},
        )
    )

    backlog_status = "ok" if pending_articles <= max_pending else "fail"
    checks.append(
        CheckResult(
            name="queue_backlog",
            status=backlog_status,
            details={"pending": pending_articles, "threshold": max_pending},
        )
    )

    ingest_status = "ok"
    ingest_details: Dict[str, Any] = {
        "latest": latest_ingest.isoformat() if latest_ingest else None,
        "threshold": max_ingest_lag_minutes,
    }

    if latest_ingest is None:
        ingest_status = "fail"
        ingest_details["message"] = "No ingestion records found"
        ingest_details["lag_minutes"] = None
    else:
        if latest_ingest.tzinfo is None:
            latest_ingest = latest_ingest.replace(tzinfo=timezone.utc)
            ingest_details["latest"] = latest_ingest.isoformat()
        lag_minutes = (now - latest_ingest).total_seconds() / 60.0
        ingest_details["lag_minutes"] = lag_minutes
        if lag_minutes > max_ingest_lag_minutes:
            ingest_status = "fail"

    checks.append(
        CheckResult(
            name="latest_ingest",
            status=ingest_status,
            details=ingest_details,
        )
    )

    healthy = all(check.status == "ok" for check in checks)

    return {
        "healthy": healthy,
        "checks": checks,
        "summary": {
            "total_articles": total_articles,
            "pending_articles": pending_articles,
            "latest_ingest": ingest_details.get("latest"),
            "ingest_lag_minutes": ingest_details.get("lag_minutes"),
        },
    }


def render_checks(checks: Iterable[CheckResult]) -> None:
    """Pretty-print the check results for CLI users."""

    for check in checks:
        print(f"{check.prefix()} {check.name}: {check.summary()}")


def run_cli(
    *,
    max_pending: Optional[int] = None,
    max_ingest_lag_minutes: Optional[int] = None,
    db_manager=None,
) -> bool:
    """Execute the healthcheck and print results."""

    setup_logging()
    result = perform_healthcheck(
        db_manager=db_manager,
        max_pending=max_pending,
        max_ingest_lag_minutes=max_ingest_lag_minutes,
    )

    checks: Iterable[CheckResult] = result.get("checks", [])
    render_checks(checks)

    if summary := result.get("summary"):
        latest = summary.get("latest_ingest")
        lag = summary.get("ingest_lag_minutes")
        pending = summary.get("pending_articles")
        print(
            "---\nSummary: "
            f"latest_ingest={latest}, lag_minutes={lag}, pending_articles={pending}"
        )

    return bool(result.get("healthy"))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Healthcheck for the Noticiencias News Collector. Validates database "
            "connectivity, queue backlog, and ingest recency."
        )
    )
    parser.add_argument(
        "--max-pending",
        type=int,
        default=None,
        help=(
            "Maximum allowed pending articles before the queue backlog check fails. "
            f"Defaults to {DEFAULT_MAX_PENDING}."
        ),
    )
    parser.add_argument(
        "--max-ingest-minutes",
        type=int,
        default=None,
        help=(
            "Maximum allowed lag in minutes between now and the latest ingest. "
            f"Defaults to {DEFAULT_MAX_INGEST_LAG_MINUTES}."
        ),
    )
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    success = run_cli(
        max_pending=args.max_pending,
        max_ingest_lag_minutes=args.max_ingest_minutes,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
