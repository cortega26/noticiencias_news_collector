"""Module role: Build the admin dashboard health evidence read (Plan 060 /
Phase 5c) from durable records only.

Owns:
- ``build_dashboard_health(db, *, now=None)``: the three backend evidence
  areas (publication, callbacks, validation) with explicit
  unknown-on-no-evidence semantics — zero rows never mean ``pass``.

Does NOT own:
- Schema/hero-image/lint health: those records are frontend-owned and are
  combined in the 5d dashboard wiring, not here.
- The HTTP route (`serving/api.py` maps this builder to the typed
  envelope) and any alerting/persistence.

Interpretation rules (documented in the phase spec):
- publication: any PUBLISHING attempt older than the publishing lease is
  ``fail``; any PR_CREATED attempt older than the reconciler's stale
  threshold is ``warning``; otherwise ``pass``.
- callbacks: any ``failed`` receipt is ``fail``; any pending ``received``
  receipt is ``warning``; otherwise ``pass``.
- validation: any ``rejected`` publication event (Content Guard blocked an
  attempt) is ``warning``; ``check_passed``-only is ``pass``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from news_collector.contracts.admin import (
    AdminDashboardEvidence,
    AdminDashboardHealthEnvelope,
    DashboardHealthStatus,
)
from news_collector.logic.workflows.pr_orchestrator import PUBLISHING_TIMEOUT_SECONDS
from news_collector.logic.workflows.publication_reconciliation import (
    DEFAULT_STALE_MINUTES,
)

_ATTEMPT_STATES = ("PUBLISHING", "PR_CREATED", "REJECTED", "COMPLETED")
_ATTEMPT_PENDING_STATES = ("PUBLISHING", "PR_CREATED")
_RECEIPT_STATUSES = ("received", "processed", "failed")
_VALIDATION_EVENT_TYPES = ("check_passed", "rejected")


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite may return tz-aware columns as naive; assume UTC (same
    precedent as ``PROrchestrator.attempt_recovery``)."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _age_seconds(now: datetime, value: datetime | None) -> int | None:
    aware = _as_utc(value)
    if aware is None:
        return None
    return max(0, int((now - aware).total_seconds()))


def _with_defaults(counts: dict[str, int], keys: tuple[str, ...]) -> dict[str, int]:
    return {key: int(counts.get(key, 0)) for key in keys}


def _publication_status(
    counts: dict[str, int],
    publishing_age: int | None,
    pr_age: int | None,
) -> tuple[DashboardHealthStatus, str]:
    """Status + detail from the two pending ages (fail beats warning)."""
    if publishing_age is not None and publishing_age > PUBLISHING_TIMEOUT_SECONDS:
        return (
            "fail",
            (
                f"{counts['PUBLISHING']} intento(s) atascado(s) en PUBLISHING "
                f"por más de {PUBLISHING_TIMEOUT_SECONDS // 60} min."
            ),
        )
    if pr_age is not None and pr_age > DEFAULT_STALE_MINUTES * 60:
        return (
            "warning",
            (
                f"{counts['PR_CREATED']} intento(s) en PR_CREATED sin callback "
                f"por más de {DEFAULT_STALE_MINUTES} min; ejecutar el "
                "reconciliador."
            ),
        )
    return (
        "pass",
        f"{sum(counts.values())} intento(s) registrados, ninguno atascado.",
    )


def _publication_evidence(db: Any, now: datetime) -> AdminDashboardEvidence:
    counts = db.lifecycle.count_publication_attempts_by_state()
    defaults = _with_defaults(counts, _ATTEMPT_STATES)
    if not counts:
        return AdminDashboardEvidence(
            status="unknown",
            evidence="none",
            detail="Sin intentos de publicación registrados.",
            counts=defaults,
        )

    publishing_age = _age_seconds(
        now, db.lifecycle.oldest_attempt_started_at("PUBLISHING")
    )
    pr_age = _age_seconds(now, db.lifecycle.oldest_attempt_started_at("PR_CREATED"))
    pending_ages = [age for age in (publishing_age, pr_age) if age is not None]
    status, detail = _publication_status(defaults, publishing_age, pr_age)

    return AdminDashboardEvidence(
        status=status,
        evidence="present",
        detail=detail,
        measured_at=db.lifecycle.latest_publication_attempt_created_at(),
        oldest_pending_age_seconds=max(pending_ages) if pending_ages else None,
        counts=defaults,
    )


def _callbacks_evidence(db: Any, now: datetime) -> AdminDashboardEvidence:
    counts = db.webhook_receipts.count_receipts_by_status()
    defaults = _with_defaults(counts, _RECEIPT_STATUSES)
    if not counts:
        return AdminDashboardEvidence(
            status="unknown",
            evidence="none",
            detail="Sin entregas de webhook registradas.",
            counts=defaults,
        )

    pending_age = _age_seconds(
        now, db.webhook_receipts.oldest_unprocessed_received_at()
    )
    measured_at = db.webhook_receipts.latest_receipt_received_at()
    if defaults["failed"]:
        return AdminDashboardEvidence(
            status="fail",
            evidence="present",
            detail=f"{defaults['failed']} entrega(s) fallida(s) sin procesar.",
            measured_at=measured_at,
            oldest_pending_age_seconds=pending_age,
            counts=defaults,
        )
    if defaults["received"]:
        return AdminDashboardEvidence(
            status="warning",
            evidence="present",
            detail=f"{defaults['received']} entrega(s) pendiente(s) de procesar.",
            measured_at=measured_at,
            oldest_pending_age_seconds=pending_age,
            counts=defaults,
        )
    return AdminDashboardEvidence(
        status="pass",
        evidence="present",
        detail=f"{defaults['processed']} entrega(s) procesada(s), ninguna pendiente.",
        measured_at=measured_at,
        oldest_pending_age_seconds=None,
        counts=defaults,
    )


def _validation_evidence(db: Any, now: datetime) -> AdminDashboardEvidence:
    counts = db.lifecycle.count_publication_events_by_type(_VALIDATION_EVENT_TYPES)
    defaults = _with_defaults(counts, _VALIDATION_EVENT_TYPES)
    if not counts:
        return AdminDashboardEvidence(
            status="unknown",
            evidence="none",
            detail="Sin resultados de Content Guard registrados.",
            counts=defaults,
        )

    measured_at = db.lifecycle.latest_publication_event_at(_VALIDATION_EVENT_TYPES)
    if defaults["rejected"]:
        return AdminDashboardEvidence(
            status="warning",
            evidence="present",
            detail=(
                f"{defaults['rejected']} intento(s) rechazado(s) por Content Guard; "
                f"{defaults['check_passed']} verificación(es) superada(s)."
            ),
            measured_at=measured_at,
            counts=defaults,
        )
    return AdminDashboardEvidence(
        status="pass",
        evidence="present",
        detail=f"{defaults['check_passed']} verificación(es) superada(s).",
        measured_at=measured_at,
        counts=defaults,
    )


def build_dashboard_health(
    db: Any, *, now: datetime | None = None
) -> AdminDashboardHealthEnvelope:
    """Assemble the dashboard evidence envelope. ``now`` is injectable for
    deterministic tests; production callers omit it."""
    reference = now or datetime.now(timezone.utc)
    return AdminDashboardHealthEnvelope(
        generated_at=reference,
        publication=_publication_evidence(db, reference),
        callbacks=_callbacks_evidence(db, reference),
        validation=_validation_evidence(db, reference),
    )
