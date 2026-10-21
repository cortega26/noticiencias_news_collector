"""Hermetic unit cover for the plan-187 reader-report admin router.

``tests/test_serving_admin_api.py`` characterizes the same routes wire-style
over the full app, but that module is marked ``e2e`` and is deselected from
the unit profile — so the changed-file coverage ratchet would see
``serving/admin_reader_reports.py`` as almost untouched. These tests drive
the router directly with a throwaway SQLite ``DatabaseManager`` and a no-op
auth dependency, mirroring the e2e assertions without the full app. Same
precedent as ``test_admin_images_router.py``.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Optional

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from news_collector.serving import admin_reader_reports
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import (
    ReaderReport,
    ReaderReportContact,
    ReaderReportDecision,
)

T1 = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)

NOTES = "la dosis del metformina está mal"


@pytest.fixture()
def db_manager(tmp_path):
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "reports.db"})
    yield manager
    manager.close()


@pytest.fixture()
def client(db_manager: DatabaseManager) -> TestClient:
    """Minimal app: only the reader-report router, auth replaced by no-op."""
    app = FastAPI()
    app.include_router(
        admin_reader_reports.build_router(lambda: None, lambda: db_manager)
    )
    return TestClient(app)


def _seed(
    db_manager: DatabaseManager,
    *,
    key: str = "idem-1",
    status: str = "new",
    created_at: Optional[datetime] = None,
    contact_email: Optional[str] = None,
    contact_purged_at: Optional[datetime] = None,
) -> int:
    with db_manager.SessionLocal() as session:
        fields = {
            "idempotency_key": key,
            "problem_type": "content_factual",
            "status": status,
        }
        if created_at is not None:
            fields["created_at"] = created_at
        report = ReaderReport(**fields)
        if contact_email is not None:
            report.contact = ReaderReportContact(email=contact_email)
        if contact_purged_at is not None:
            report.contact_purged_at = contact_purged_at
        session.add(report)
        session.commit()
        return int(report.id)


def _seed_decision(
    db_manager: DatabaseManager,
    report_id: int,
    *,
    decision: str = "no_action",
    actor: str = "alaria",
) -> None:
    with db_manager.SessionLocal() as session:
        session.add(
            ReaderReportDecision(report_id=report_id, decision=decision, actor=actor)
        )
        session.commit()


def _decide(client: TestClient, report_id: int, payload: dict) -> object:
    return client.post(f"/v1/admin/reader-reports/{report_id}/decisions", json=payload)


def _decision_payload(**overrides: object) -> dict:
    body: dict[str, object] = {"actor": "alaria", "notes": NOTES}
    body.update(overrides)
    return body


def _count(db_manager: DatabaseManager, model) -> int:
    with db_manager.SessionLocal() as session:
        return int(
            session.execute(select(func.count()).select_from(model)).scalar_one()
        )


# ---------------------------------------------------------------------------
# Cursor codec (direct unit cover + one route-level 400)
# ---------------------------------------------------------------------------


class TestCursorCodec:
    def test_roundtrip_encodes_created_at_and_id(self) -> None:
        row = ReaderReport(id=7)
        row.created_at = T2
        encoded = admin_reader_reports._encode_report_cursor(row)
        assert admin_reader_reports._decode_report_cursor(encoded) == (T2, 7)

    def test_encode_falls_back_to_epoch_when_created_at_missing(self) -> None:
        row = ReaderReport(id=3)  # untouched instance: created_at is None
        encoded = admin_reader_reports._encode_report_cursor(row)
        payload = json.loads(
            base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")
        )
        assert payload[0] == "1970-01-01T00:00:00"
        assert admin_reader_reports._decode_report_cursor(encoded)[1] == 3

    @pytest.mark.parametrize(
        "raw",
        [
            "not!base64!",  # binascii failure
            base64.urlsafe_b64encode(b'{"shape": "dict"}').decode("ascii"),
            base64.urlsafe_b64encode(b'["one"]').decode("ascii"),  # arity
            base64.urlsafe_b64encode(b'["not-a-date", 7]').decode("ascii"),
            base64.urlsafe_b64encode(b'["2026-10-20T09:00:00", 0]').decode("ascii"),
        ],
    )
    def test_malformed_cursor_refused_with_400(self, raw: str) -> None:
        with pytest.raises(HTTPException) as exc_info:
            admin_reader_reports._decode_report_cursor(raw)
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid cursor"

    def test_decode_refuses_non_ascii_input(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            admin_reader_reports._decode_report_cursor("\xff\xfe-not-ascii")
        assert exc_info.value.status_code == 400

    def test_route_maps_bad_cursor_to_400(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        _seed(db_manager)
        response = client.get(
            "/v1/admin/reader-reports", params={"cursor": "not!base64!"}
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid cursor"


# ---------------------------------------------------------------------------
# Filter validation
# ---------------------------------------------------------------------------


class TestFilterValidation:
    @pytest.mark.parametrize(
        "validator, valid",
        [
            (admin_reader_reports._validated_status_filter, "new"),
            (admin_reader_reports._validated_resolution_filter, "resolved"),
            (admin_reader_reports._validated_problem_type_filter, "content_factual"),
        ],
    )
    def test_valid_values_pass_through(self, validator, valid: str) -> None:
        assert validator("all") == "all"
        assert validator(valid) == valid

    @pytest.mark.parametrize(
        "validator, refusal",
        [
            (admin_reader_reports._validated_status_filter, "bogus-status"),
            (admin_reader_reports._validated_resolution_filter, "bogus-res"),
            (admin_reader_reports._validated_problem_type_filter, "bogus-type"),
        ],
    )
    def test_invalid_filter_raises_422_with_valid_list(
        self, validator, refusal: str
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            validator(refusal)
        assert exc_info.value.status_code == 422
        assert "Valid:" in str(exc_info.value.detail)

    def test_route_rejects_invalid_filters_with_422(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        _seed(db_manager)
        for param_name in ("status", "resolution", "problem_type"):
            response = client.get(
                "/v1/admin/reader-reports", params={param_name: "bogus"}
            )
            assert response.status_code == 422
            assert "Valid:" in response.json()["detail"]


# ---------------------------------------------------------------------------
# List endpoint
# ---------------------------------------------------------------------------


class TestListEndpoint:
    def test_list_maps_items_without_any_email_field(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed(db_manager, created_at=T2, contact_email="reader@example.com")

        response = client.get("/v1/admin/reader-reports")
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["pagination"]["page_size"] == 20
        assert envelope["pagination"]["has_more"] is False
        assert envelope["pagination"]["next_cursor"] is None
        assert envelope["pagination"]["returned"] == 1
        assert envelope["filters"] == {
            "status": "all",
            "resolution": "all",
            "problem_type": "all",
        }
        assert envelope["meta"]["generated_at"]

        (item,) = envelope["data"]
        assert item["id"] == report_id
        assert item["status"] == "new"
        assert item["problem_type"] == "content_factual"
        assert item["decision_count"] == 0
        assert item["latest_decision"] is None
        assert "reporter_email" not in item.keys()  # privacy: absent field
        assert "reporter_email" not in response.text

    def test_list_orders_newest_first_and_applies_filters(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        first = _seed(db_manager, key="idem-1", created_at=T1)
        second = _seed(db_manager, key="idem-2", created_at=T2)

        response = client.get("/v1/admin/reader-reports", params={"status": "new"})
        ids = [item["id"] for item in response.json()["data"]]
        assert ids == [second, first]

        # The other two filter legs execute against real values too.
        resolution = client.get(
            "/v1/admin/reader-reports", params={"resolution": "unresolved"}
        )
        assert [item["id"] for item in resolution.json()["data"]] == [second, first]

        typed = client.get(
            "/v1/admin/reader-reports", params={"problem_type": "technical_site"}
        )
        assert typed.json()["data"] == []
        assert typed.json()["filters"]["problem_type"] == "technical_site"

        only_triaged = client.get(
            "/v1/admin/reader-reports", params={"status": "triaged"}
        )
        assert only_triaged.status_code == 200
        assert only_triaged.json()["data"] == []

    def test_list_decision_count_and_latest(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed(db_manager)
        _seed_decision(db_manager, report_id, decision="no_action")

        response = client.get("/v1/admin/reader-reports")
        (item,) = response.json()["data"]
        assert item["decision_count"] == 1
        assert item["latest_decision"]["decision"] == "no_action"
        assert item["latest_decision"]["actor"] == "alaria"
        assert "reporter_email" not in item.keys()

    def test_list_cursor_pagination(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        _seed(db_manager, key="idem-1", created_at=T1)
        _seed(db_manager, key="idem-2", created_at=T2)

        page_one = client.get("/v1/admin/reader-reports", params={"page_size": 1})
        assert page_one.status_code == 200
        pagination = page_one.json()["pagination"]
        assert pagination["has_more"] is True
        assert pagination["next_cursor"]
        assert [item["id"] for item in page_one.json()["data"]] == [2]  # T2 first

        page_two = client.get(
            "/v1/admin/reader-reports",
            params={"page_size": 1, "cursor": pagination["next_cursor"]},
        )
        assert page_two.status_code == 200
        pagination_two = page_two.json()["pagination"]
        assert pagination_two["has_more"] is False
        assert pagination_two["next_cursor"] is None
        assert [item["id"] for item in page_two.json()["data"]] == [1]

    def test_list_empty_reports(self, client: TestClient) -> None:
        response = client.get("/v1/admin/reader-reports")
        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert body["pagination"]["has_more"] is False

    def test_list_rejects_zero_page_size(self, client: TestClient) -> None:
        response = client.get("/v1/admin/reader-reports", params={"page_size": 0})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Detail endpoint
# ---------------------------------------------------------------------------


class TestDetailEndpoint:
    def test_detail_404_for_missing_report(self, client: TestClient) -> None:
        response = client.get("/v1/admin/reader-reports/4242")
        assert response.status_code == 404
        assert response.json()["detail"] == "Reader report not found"
        assert "reporter_email" not in response.text

    def test_detail_carries_email_only_when_contact_and_not_purged(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        live = _seed(db_manager, key="idem-1", contact_email="reader@example.com")
        purged = _seed(
            db_manager,
            key="idem-2",
            contact_email="purged@example.com",
            contact_purged_at=T2,
        )
        bare = _seed(db_manager, key="idem-3")

        live_body = client.get(f"/v1/admin/reader-reports/{live}").json()
        assert live_body["reporter_email"] == "reader@example.com"
        assert live_body["decisions"] == []

        purged_body = client.get(f"/v1/admin/reader-reports/{purged}").json()
        # The contact row still exists, but the purge stamp wins: after a
        # purge the email never leaves the backend.
        assert purged_body["reporter_email"] is None

        bare_body = client.get(f"/v1/admin/reader-reports/{bare}").json()
        assert bare_body["reporter_email"] is None

    def test_detail_orders_decisions_oldest_first(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed(db_manager)
        _seed_decision(db_manager, report_id, decision="no_action", actor="pri")
        _seed_decision(db_manager, report_id, decision="rejected", actor="seg")

        body = client.get(f"/v1/admin/reader-reports/{report_id}").json()
        assert body["decision_count"] == 2
        assert [row["decision"] for row in body["decisions"]] == [
            "no_action",
            "rejected",
        ]
        assert body["latest_decision"]["decision"] == "rejected"

    def test_detail_decision_item_fields(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed(db_manager)
        with db_manager.SessionLocal() as session:
            session.add(
                ReaderReportDecision(
                    report_id=report_id,
                    decision="accepted",
                    actor="alaria",
                    notes="revisado",
                    corrected_at=T1,
                    correction_summary="la dosis era 1 mg",
                )
            )
            session.commit()

        body = client.get(f"/v1/admin/reader-reports/{report_id}").json()
        (row,) = body["decisions"]
        assert row["decision"] == "accepted"
        assert row["notes"] == "revisado"
        assert row["correction_summary"] == "la dosis era 1 mg"
        assert row["corrected_at"]
        assert row["publication_ref"] is None
        assert row["deploy_evidence"] is None
        assert row["closed_at"] is None
        assert row["duplicate_of_report_id"] is None


# ---------------------------------------------------------------------------
# Decision POST endpoint
# ---------------------------------------------------------------------------


class TestDecisionEndpoint:
    def test_post_404_for_missing_report(self, client: TestClient) -> None:
        response = _decide(client, 4242, _decision_payload(decision="no_action"))
        assert response.status_code == 404
        assert response.json()["detail"] == "Reader report not found"

    def test_post_decision_applies_with_header(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed(db_manager)

        response = _decide(client, report_id, _decision_payload(decision="no_action"))
        assert response.status_code == 200
        assert response.headers["X-Reader-Report-Decision"] == "applied"
        body = response.json()
        assert body["action"] == "decision"
        assert body["replayed"] is False
        assert body["replayed_decision_id"] is None
        assert body["inserted_decision_id"] > 0
        assert body["report"]["status"] == "no_action"
        assert body["report"]["decision_count"] == 1

    def test_post_triage_moves_new_and_appends_no_row(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed(db_manager)

        response = _decide(client, report_id, _decision_payload(kind="triage"))
        assert response.status_code == 200
        assert response.headers["X-Reader-Report-Decision"] == "triaged"
        body = response.json()
        assert body["action"] == "triage"
        assert body["inserted_decision_id"] is None
        assert body["report"]["status"] == "triaged"
        assert body["report"]["decision_count"] == 0
        assert _count(db_manager, ReaderReportDecision) == 0

    def test_post_exact_replay_is_idempotent(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed(db_manager)
        payload = _decision_payload(decision="no_action")

        first = _decide(client, report_id, payload)
        assert first.status_code == 200
        assert first.headers["X-Reader-Report-Decision"] == "applied"
        assert first.json()["inserted_decision_id"] > 0

        second = _decide(client, report_id, payload)
        assert second.status_code == 200
        assert second.headers["X-Reader-Report-Decision"] == "replayed"
        body = second.json()
        assert body["replayed"] is True
        assert body["replayed_decision_id"] == first.json()["inserted_decision_id"]
        assert body["inserted_decision_id"] is None
        assert body["report"]["status"] == "no_action"
        assert _count(db_manager, ReaderReportDecision) == 1

    def test_post_redecision_changed_payload_appends_second_row(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed(db_manager)
        _decide(client, report_id, _decision_payload(decision="no_action"))

        response = _decide(
            client,
            report_id,
            _decision_payload(decision="rejected", notes="mejor revisado"),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["inserted_decision_id"] > 0
        assert body["report"]["status"] == "rejected"
        assert body["report"]["decision_count"] == 2

    def test_post_refuses_triage_only_from_new(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed(db_manager, status="triaged")
        response = _decide(client, report_id, _decision_payload(kind="triage"))
        assert response.status_code == 409
        assert "triage_only_from_new" in response.json()["detail"]

    def test_post_triage_refuses_decision_fields(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed(db_manager)
        response = _decide(
            client,
            report_id,
            _decision_payload(kind="triage", decision="no_action"),
        )
        assert response.status_code == 422
        assert "triage_extra_fields" in response.json()["detail"]

    def test_post_decision_without_kind_value_refused(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed(db_manager)
        response = _decide(client, report_id, _decision_payload())  # no decision
        assert response.status_code == 422
        assert "decision_missing" in response.json()["detail"]

    def test_post_accepted_without_correction_evidence_refused(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed(db_manager)
        response = _decide(client, report_id, _decision_payload(decision="accepted"))
        assert response.status_code == 422
        assert "accepted_missing_correction" in response.json()["detail"]

    def test_post_correction_fields_rejected_on_other_kinds(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed(db_manager)
        response = _decide(
            client,
            report_id,
            _decision_payload(decision="rejected", correction_summary="x"),
        )
        assert response.status_code == 422
        assert "decision_extra_fields" in response.json()["detail"]

    def test_post_duplicate_without_reference_refused(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed(db_manager)
        response = _decide(client, report_id, _decision_payload(decision="duplicate"))
        assert response.status_code == 422
        assert "duplicate_missing_ref" in response.json()["detail"]

    def test_post_duplicate_self_reference_refused(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed(db_manager)
        response = _decide(
            client,
            report_id,
            _decision_payload(decision="duplicate", duplicate_of_report_id=report_id),
        )
        assert response.status_code == 409
        assert "duplicate_self_reference" in response.json()["detail"]

    def test_post_duplicate_target_missing_refused(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed(db_manager)
        response = _decide(
            client,
            report_id,
            _decision_payload(decision="duplicate", duplicate_of_report_id=9999),
        )
        assert response.status_code == 409
        assert "duplicate_target_missing" in response.json()["detail"]

    def test_post_duplicate_reference_rejected_on_other_kinds(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed(db_manager)
        response = _decide(
            client,
            report_id,
            _decision_payload(decision="rejected", duplicate_of_report_id=99),
        )
        assert response.status_code == 422
        assert "duplicate_ref_not_applicable" in response.json()["detail"]

    def test_post_duplicate_reference_happy_path(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        target_id = _seed(db_manager, key="idem-2")
        report_id = _seed(db_manager)

        response = _decide(
            client,
            report_id,
            _decision_payload(decision="duplicate", duplicate_of_report_id=target_id),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["inserted_decision_id"] > 0
        assert body["report"]["status"] == "duplicate"
        assert body["report"]["latest_decision"]["duplicate_of_report_id"] == target_id

    def test_post_accepted_happy_path_with_email_privacy(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed(db_manager, contact_email="reader@example.com")

        response = _decide(
            client,
            report_id,
            _decision_payload(
                decision="accepted",
                corrected_at=T1.isoformat(),
                correction_summary="la dosis era 1 mg",
            ),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["report"]["status"] == "accepted"
        # Detail carries the email ONLY while contact is present & not purged.
        assert body["report"]["reporter_email"] == "reader@example.com"

    def test_post_contract_refuses_blank_notes(
        self, client: TestClient, db_manager: DatabaseManager
    ) -> None:
        report_id = _seed(db_manager)
        response = _decide(
            client,
            report_id,
            _decision_payload(decision="no_action", notes="   "),
        )
        assert response.status_code == 422  # contract layer (pydantic)
        errors = response.json()["detail"]
        assert any(error["loc"][-1] == "notes" for error in errors)

    def test_stale_conflict_maps_to_409(
        self,
        client: TestClient,
        db_manager: DatabaseManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Force the CAS to lose: the context reports status 'new' while the
        # row actually holds 'triaged' by the time the UPDATE runs.
        from news_collector.contracts.reader_reports import DecisionContext

        report_id = _seed(db_manager, status="triaged")

        def stale_context(session, report, request):
            return DecisionContext(
                report_id=report.id,
                current_status="new",  # the snapshot lies about the row
                duplicate_of_exists=None,
                replayed_decision_id=None,
            )

        monkeypatch.setattr(
            admin_reader_reports, "build_decision_context", stale_context
        )

        response = _decide(client, report_id, _decision_payload(decision="no_action"))
        assert response.status_code == 409
        assert "changed concurrently" in response.json()["detail"]
        # Nothing was appended.
        assert _count(db_manager, ReaderReportDecision) == 0

    def test_rule_status_map_covers_every_stable_reason_enumeration(self) -> None:
        # The full mapping is asserted exactly: refusing a reason list to
        # drift (missing causes 500s; extra entries hide dead codes).
        from news_collector.logic.workflows import report_decisions as rules

        assert admin_reader_reports._RULE_HTTP_STATUS == {
            rules.VIOLATION_EMPTY_ACTOR: 422,
            rules.VIOLATION_EMPTY_NOTES: 422,
            rules.VIOLATION_CLOSED_LOCKED: 409,
            rules.VIOLATION_UNKNOWN_CURRENT_STATUS: 409,
            rules.VIOLATION_TRIAGE_EXTRA_FIELDS: 422,
            rules.VIOLATION_TRIAGE_ONLY_FROM_NEW: 409,
            rules.VIOLATION_MISSING_DECISION_KIND: 422,
            rules.VIOLATION_DECISION_EXTRA_FIELDS: 422,
            rules.VIOLATION_ACCEPTED_MISSING_CORRECTION: 422,
            rules.VIOLATION_DUPLICATE_MISSING_REF: 422,
            rules.VIOLATION_DUPLICATE_REF_NOT_APPLICABLE: 422,
            rules.VIOLATION_DUPLICATE_SELF_REFERENCE: 409,
            rules.VIOLATION_DUPLICATE_TARGET_MISSING: 409,
        }
