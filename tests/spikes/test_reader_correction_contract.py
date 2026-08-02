"""
Plan 047 — Reader correction loop contract prototype (SPIKE).

This is a synthetic, non-production state-machine prototype that tests
whether the correction lifecycle contract is sound. It does NOT touch
network, production storage, or real reporter data.

Run: .venv/bin/python -m pytest tests/spikes/test_reader_correction_contract.py -q
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import pytest


class ReportStatus(str, Enum):
    RECEIVED = "received"
    TRIAGED = "triaged"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"
    ACCEPTED = "accepted"
    CORRECTION_PROPOSED = "correction_proposed"
    CORRECTION_PUBLISHED = "correction_published"
    CLOSED = "closed"


class ReportType(str, Enum):
    FACTUAL_ERROR = "factual_error"
    TYPO = "typo"
    BROKEN_LINK = "broken_link"
    OUTDATED = "outdated"
    OTHER = "other"


@dataclass
class ReportEvent:
    timestamp: str
    actor: str
    action: str
    reason: str = ""


@dataclass
class ReportEnvelope:
    """Versioned report/correction envelope (synthetic prototype)."""

    report_id: str
    public_url: str
    refinery_id: str | None = None
    content_revision: str = ""
    type: ReportType = ReportType.OTHER
    description: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    consent_contact: bool = False
    consent_attribution: bool = False
    contact: str | None = None  # Deleted on closure
    status: ReportStatus = ReportStatus.RECEIVED
    events: list[ReportEvent] = field(default_factory=list)

    @property
    def idempotency_key(self) -> str:
        raw = f"{self.public_url}:{self.type.value}:{self.content_revision}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def transition(
        self, new_status: ReportStatus, actor: str, reason: str = ""
    ) -> None:
        allowed = {
            ReportStatus.RECEIVED: {ReportStatus.TRIAGED},
            ReportStatus.TRIAGED: {
                ReportStatus.DUPLICATE,
                ReportStatus.REJECTED,
                ReportStatus.ACCEPTED,
            },
            ReportStatus.ACCEPTED: {ReportStatus.CORRECTION_PROPOSED},
            ReportStatus.CORRECTION_PROPOSED: {ReportStatus.CORRECTION_PUBLISHED},
            ReportStatus.CORRECTION_PUBLISHED: {ReportStatus.CLOSED},
            ReportStatus.DUPLICATE: set(),
            ReportStatus.REJECTED: set(),
            ReportStatus.CLOSED: set(),
        }
        if new_status not in allowed.get(self.status, set()):
            raise ValueError(
                f"Invalid transition: {self.status.value} -> {new_status.value}"
            )
        self.status = new_status
        self.events.append(
            ReportEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                actor=actor,
                action=new_status.value,
                reason=reason,
            )
        )

    def close(self) -> None:
        """Delete contact data on closure (privacy)."""
        self.contact = None


def make_report(
    url: str = "https://noticiencias.com/some-article",
    type: ReportType = ReportType.FACTUAL_ERROR,
    revision: str = "abc123",
    description: str = "The article says 42 but the correct value is 43.",
    contact: str | None = "reporter@example.com",
) -> ReportEnvelope:
    return ReportEnvelope(
        report_id=str(uuid.uuid4()),
        public_url=url,
        content_revision=revision,
        type=type,
        description=description,
        contact=contact,
        consent_contact=True,
    )


# ─── Tests ────────────────────────────────────────────────────────────────


class TestLifecycle:
    def test_happy_path(self):
        report = make_report()
        report.transition(ReportStatus.TRIAGED, "editor", "acknowledged")
        report.transition(ReportStatus.ACCEPTED, "editor", "verified")
        report.transition(ReportStatus.CORRECTION_PROPOSED, "editor", "PR #123")
        report.transition(ReportStatus.CORRECTION_PUBLISHED, "bot", "PR merged")
        report.transition(ReportStatus.CLOSED, "editor", "confirmed")
        assert report.status == ReportStatus.CLOSED
        assert len(report.events) == 5

    def test_skip_triage_rejected(self):
        report = make_report()
        with pytest.raises(ValueError, match="Invalid transition"):
            report.transition(ReportStatus.REJECTED, "editor")

    def test_close_before_published(self):
        report = make_report()
        report.transition(ReportStatus.TRIAGED, "editor")
        report.transition(ReportStatus.ACCEPTED, "editor")
        with pytest.raises(ValueError, match="Invalid transition"):
            report.transition(ReportStatus.CLOSED, "editor")

    def test_duplicate_is_terminal(self):
        report = make_report()
        report.transition(ReportStatus.TRIAGED, "editor")
        report.transition(ReportStatus.DUPLICATE, "editor", "dup of #456")
        with pytest.raises(ValueError, match="Invalid transition"):
            report.transition(ReportStatus.ACCEPTED, "editor")

    def test_rejected_is_terminal(self):
        report = make_report()
        report.transition(ReportStatus.TRIAGED, "editor")
        report.transition(ReportStatus.REJECTED, "editor", "not actionable")
        with pytest.raises(ValueError, match="Invalid transition"):
            report.transition(ReportStatus.ACCEPTED, "editor")

    def test_closed_is_terminal(self):
        report = make_report()
        report.transition(ReportStatus.TRIAGED, "editor")
        report.transition(ReportStatus.ACCEPTED, "editor")
        report.transition(ReportStatus.CORRECTION_PROPOSED, "editor")
        report.transition(ReportStatus.CORRECTION_PUBLISHED, "bot")
        report.transition(ReportStatus.CLOSED, "editor")
        with pytest.raises(ValueError, match="Invalid transition"):
            report.transition(ReportStatus.TRIAGED, "editor")

    def test_transition_with_empty_reason(self):
        report = make_report()
        report.transition(ReportStatus.TRIAGED, "editor")  # reason defaults to ""
        assert report.events[-1].reason == ""

    def test_no_contact_report(self):
        report = make_report(contact=None)
        assert report.contact is None
        report.transition(ReportStatus.TRIAGED, "editor")
        report.transition(ReportStatus.REJECTED, "editor", "no contact")
        report.close()
        assert report.contact is None


class TestIdempotency:
    def test_same_report_same_key(self):
        r1 = make_report(
            url="https://noticiencias.com/a",
            type=ReportType.FACTUAL_ERROR,
            revision="v1",
        )
        r2 = make_report(
            url="https://noticiencias.com/a",
            type=ReportType.FACTUAL_ERROR,
            revision="v1",
        )
        assert r1.idempotency_key == r2.idempotency_key

    def test_different_url_different_key(self):
        r1 = make_report(url="https://noticiencias.com/a")
        r2 = make_report(url="https://noticiencias.com/b")
        assert r1.idempotency_key != r2.idempotency_key

    def test_different_type_different_key(self):
        r1 = make_report(type=ReportType.FACTUAL_ERROR)
        r2 = make_report(type=ReportType.TYPO)
        assert r1.idempotency_key != r2.idempotency_key


class TestPrivacy:
    def test_contact_deleted_on_close(self):
        report = make_report(contact="reporter@example.com")
        assert report.contact == "reporter@example.com"
        report.transition(ReportStatus.TRIAGED, "editor")
        report.transition(ReportStatus.ACCEPTED, "editor")
        report.transition(ReportStatus.CORRECTION_PROPOSED, "editor")
        report.transition(ReportStatus.CORRECTION_PUBLISHED, "bot")
        report.transition(ReportStatus.CLOSED, "editor")
        report.close()
        assert report.contact is None

    def test_no_contact_field_in_events(self):
        report = make_report(contact="secret@example.com")
        report.transition(ReportStatus.TRIAGED, "editor")
        for event in report.events:
            assert "secret@example.com" not in event.reason
            assert "secret@example.com" not in event.action


class TestIdentityResolution:
    def test_refinery_id_resolved(self):
        report = make_report()
        report.refinery_id = "2026-01-15-some-article"
        assert report.refinery_id is not None

    def test_refinery_id_none_for_unknown(self):
        report = make_report(url="https://noticiencias.com/nonexistent")
        assert report.refinery_id is None
