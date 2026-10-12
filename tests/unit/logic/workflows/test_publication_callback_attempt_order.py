"""Adversarial tests for callbacks correlated across publication attempts."""

from __future__ import annotations

import hashlib
from datetime import datetime

import pytest

from news_collector.contracts.webhook import PublishCompleteEvent, ValidationResultEvent
from news_collector.logic.workflows.publication_callbacks import (
    apply_publish_complete,
    apply_validation_result,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article

ARTICLE_URL = "https://example.com/callback-attempt-order"
REFINERY_ID = "article-2422-fixture"
DEPLOY_URL = "https://noticiencias.com"
PR_URL = "https://github.com/cortega26/noticiencias/pull/{number}"


@pytest.fixture()
def db_manager(tmp_path) -> DatabaseManager:
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "callbacks.db"})
    with manager.get_session() as session:
        session.add(
            Article(
                title="Callback attempt order",
                url=ARTICLE_URL,
                summary="A temporary callback fixture",
                source_id="test-source",
                source_name="Test Source",
                category="science",
                processing_status="pending",
            )
        )
    yield manager
    manager.close()


def _article(db: DatabaseManager) -> Article:
    with db.get_session() as session:
        row = session.query(Article).filter_by(url=ARTICLE_URL).one()
        session.expunge(row)
        return row


def _start_attempt(
    db: DatabaseManager,
    article_id: int,
    *,
    pull_request_number: int,
    content: bytes,
) -> tuple[object, dict[str, object]]:
    attempt_token = f"internal-attempt-{pull_request_number}"
    content_sha256 = hashlib.sha256(content).hexdigest()
    branch = f"content/update-attempt-{pull_request_number}"
    assert db.mark_article_publishing(
        article_id, branch, publication_attempt_id=attempt_token
    )
    assert db.mark_article_published(
        article_id,
        PR_URL.format(number=pull_request_number),
        REFINERY_ID,
        publication_attempt_id=attempt_token,
        content_sha256=content_sha256,
    )
    attempt = db.lifecycle.get_publication_attempts_for_article(article_id)[-1]
    ref: dict[str, object] = {
        "refinery_id": REFINERY_ID,
        "pull_request_number": pull_request_number,
        "content_sha256": content_sha256,
    }
    return attempt, ref


def _validation(
    *,
    status: str,
    refs: list[dict[str, object]],
    publication_ids: list[str] | None = None,
    delivery_id: str | None = None,
) -> ValidationResultEvent:
    payload: dict[str, object] = {
        "event": "validation_result",
        "commit_sha": "validation-commit",
        "branch": "content/update-test",
        "status": status,
        "diagnostics": [{"check": "content-guard", "status": status}],
        "frontend_ref": "validation-commit",
        "run_url": "https://github.com/cortega26/noticiencias/actions/runs/100",
        "publication_ids": publication_ids or [REFINERY_ID],
        "publication_attempt_refs": refs,
    }
    if delivery_id:
        payload["delivery_id"] = delivery_id
    return ValidationResultEvent.model_validate(payload)


def _deploy(
    refs: list[dict[str, object]],
    *,
    publication_ids: list[str] | None = None,
    delivery_id: str | None = None,
) -> PublishCompleteEvent:
    payload: dict[str, object] = {
        "event": "publish_complete",
        "commit_sha": "deployed-commit",
        "branch": "main",
        "status": "success",
        "diagnostics": [
            {"check": "deploy", "status": "pass", "deploy_url": DEPLOY_URL}
        ],
        "frontend_ref": "deployed-commit",
        "run_url": "https://github.com/cortega26/noticiencias/actions/runs/200",
        "publication_ids": publication_ids or [REFINERY_ID],
        "publication_attempt_refs": refs,
    }
    if delivery_id:
        payload["delivery_id"] = delivery_id
    return PublishCompleteEvent.model_validate(payload)


def _attempts(db: DatabaseManager, article_id: int) -> list[object]:
    return db.lifecycle.get_publication_attempts_for_article(article_id)


def _event_types(db: DatabaseManager, attempt_id: int) -> list[str]:
    return [
        event.event_type
        for event in db.lifecycle.get_publication_events_for_attempt(attempt_id)
    ]


def test_validation_pass_then_deploy_completes_once(db_manager: DatabaseManager):
    article_id = int(_article(db_manager).id)
    attempt, ref = _start_attempt(
        db_manager,
        article_id,
        pull_request_number=101,
        content=b"approved exact markdown bytes",
    )

    passed = apply_validation_result(
        _validation(status="pass", refs=[ref], delivery_id="pass-101"), db_manager
    )
    before_deploy = _article(db_manager)
    deployed = apply_publish_complete(
        _deploy([ref], delivery_id="deploy-101"), db_manager
    )
    first_published_at = _article(db_manager).published_at
    duplicate = apply_publish_complete(
        _deploy([ref], delivery_id="deploy-101"), db_manager
    )

    current = _article(db_manager)
    lifecycle_attempt = _attempts(db_manager, article_id)[0]
    assert passed["recorded"] == 1
    assert before_deploy.processing_status == "publishing"
    assert deployed["updated"] == 1
    assert current.processing_status == "completed"
    assert lifecycle_attempt.state == "COMPLETED"
    assert current.published_at == first_published_at
    assert isinstance(current.published_at, datetime)
    assert current.published_url == DEPLOY_URL
    assert _event_types(db_manager, attempt.id).count("deployed") == 1
    assert _event_types(db_manager, attempt.id).count("check_passed") == 1
    assert duplicate["duplicates"] == 1
    assert duplicate["updated"] == 0
    assert duplicate["conflicts"] == 0
    assert duplicate["needs_attention"] is False


def test_authentic_validation_failure_without_deploy_rejects_exact_attempt(
    db_manager: DatabaseManager,
):
    article_id = int(_article(db_manager).id)
    attempt, ref = _start_attempt(
        db_manager,
        article_id,
        pull_request_number=102,
        content=b"failed exact markdown bytes",
    )

    result = apply_validation_result(_validation(status="fail", refs=[ref]), db_manager)

    current = _article(db_manager)
    lifecycle_attempt = _attempts(db_manager, article_id)[0]
    assert result["updated"] == 1
    assert current.processing_status == "rejected"
    assert current.published_at is None
    assert current.published_url is None
    assert lifecycle_attempt.state == "REJECTED"
    assert _event_types(db_manager, attempt.id).count("rejected") == 1
    assert "deployed" not in _event_types(db_manager, attempt.id)


def test_stale_failure_then_later_authentic_deploy_completes_current_attempt(
    db_manager: DatabaseManager,
):
    article_id = int(_article(db_manager).id)
    old_attempt, old_ref = _start_attempt(
        db_manager,
        article_id,
        pull_request_number=103,
        content=b"old attempt content",
    )
    current_attempt, current_ref = _start_attempt(
        db_manager,
        article_id,
        pull_request_number=104,
        content=b"later attempt content",
    )

    failed_old = apply_validation_result(
        _validation(status="fail", refs=[old_ref]), db_manager
    )
    current_while_waiting = _article(db_manager)
    deployed_current = apply_publish_complete(_deploy([current_ref]), db_manager)

    current = _article(db_manager)
    attempts = _attempts(db_manager, article_id)
    assert failed_old["updated"] == 1
    assert failed_old["article_updated"] == 0
    assert current_while_waiting.processing_status == "publishing"
    assert [attempt.state for attempt in attempts] == ["REJECTED", "COMPLETED"]
    assert deployed_current["updated"] == 1
    assert current.processing_status == "completed"
    assert current.published_at is not None
    assert current.published_url == DEPLOY_URL
    assert _event_types(db_manager, old_attempt.id).count("rejected") == 1
    assert _event_types(db_manager, current_attempt.id).count("deployed") == 1


def test_late_failure_cannot_reject_deployed_attempt_or_article(
    db_manager: DatabaseManager,
):
    article_id = int(_article(db_manager).id)
    attempt, ref = _start_attempt(
        db_manager,
        article_id,
        pull_request_number=105,
        content=b"content deployed before delayed validation callback",
    )

    assert apply_publish_complete(_deploy([ref]), db_manager)["updated"] == 1
    late_failure = apply_validation_result(
        _validation(status="fail", refs=[ref]), db_manager
    )

    current = _article(db_manager)
    lifecycle_attempt = _attempts(db_manager, article_id)[0]
    assert late_failure["updated"] == 0
    assert late_failure["conflicts"] == 1
    assert late_failure["needs_attention"] is True
    assert current.processing_status == "completed"
    assert current.published_at is not None
    assert current.published_url == DEPLOY_URL
    assert lifecycle_attempt.state == "COMPLETED"
    assert _event_types(db_manager, attempt.id).count("deployed") == 1
    assert "rejected" not in _event_types(db_manager, attempt.id)


def test_unmatched_deploy_cannot_override_an_authentic_failure(
    db_manager: DatabaseManager,
):
    article_id = int(_article(db_manager).id)
    attempt, ref = _start_attempt(
        db_manager,
        article_id,
        pull_request_number=106,
        content=b"failed content with no matching deployed evidence",
    )
    assert (
        apply_validation_result(_validation(status="fail", refs=[ref]), db_manager)[
            "updated"
        ]
        == 1
    )
    uncorrelated_ref = {
        **ref,
        "content_sha256": hashlib.sha256(b"different deployed bytes").hexdigest(),
    }

    result = apply_publish_complete(_deploy([uncorrelated_ref]), db_manager)

    current = _article(db_manager)
    lifecycle_attempt = _attempts(db_manager, article_id)[0]
    assert result["updated"] == 0
    assert result["needs_attention"] is True
    assert result["unmatched"] == 1
    assert current.processing_status == "rejected"
    assert current.published_at is None
    assert current.published_url is None
    assert lifecycle_attempt.state == "REJECTED"
    assert _event_types(db_manager, attempt.id).count("deployed") == 0


def test_callback_for_one_attempt_does_not_mutate_another_attempt(
    db_manager: DatabaseManager,
):
    article_id = int(_article(db_manager).id)
    first, first_ref = _start_attempt(
        db_manager,
        article_id,
        pull_request_number=107,
        content=b"first article attempt",
    )
    second, second_ref = _start_attempt(
        db_manager,
        article_id,
        pull_request_number=108,
        content=b"second article attempt",
    )

    result = apply_validation_result(
        _validation(status="fail", refs=[first_ref]), db_manager
    )

    current = _article(db_manager)
    attempts = _attempts(db_manager, article_id)
    assert result["updated"] == 1
    assert [attempt.state for attempt in attempts] == ["REJECTED", "PR_CREATED"]
    assert current.processing_status == "publishing"
    assert current.published_at is None
    assert current.published_url is None
    assert _event_types(db_manager, first.id).count("rejected") == 1
    assert "rejected" not in _event_types(db_manager, second.id)
    assert _event_types(db_manager, second.id) == ["pr_created"]
    assert second_ref["pull_request_number"] == 108


def test_duplicate_validation_and_deploy_retries_are_idempotent(
    db_manager: DatabaseManager,
):
    article_id = int(_article(db_manager).id)
    rejected_attempt, rejected_ref = _start_attempt(
        db_manager,
        article_id,
        pull_request_number=109,
        content=b"content rejected exactly once",
    )
    fail_event = _validation(
        status="fail", refs=[rejected_ref], delivery_id="same-failure-delivery"
    )
    first_failure = apply_validation_result(fail_event, db_manager)
    second_failure = apply_validation_result(fail_event, db_manager)

    assert first_failure["updated"] == 1
    assert second_failure["updated"] == 0
    assert second_failure["duplicates"] == 1
    assert second_failure["conflicts"] == 0
    assert second_failure["needs_attention"] is False
    assert _event_types(db_manager, rejected_attempt.id).count("rejected") == 1

    deployed_attempt, deployed_ref = _start_attempt(
        db_manager,
        article_id,
        pull_request_number=110,
        content=b"content deployed exactly once",
    )
    deploy_event = _deploy([deployed_ref], delivery_id="same-deploy-delivery")
    first_deploy = apply_publish_complete(deploy_event, db_manager)
    completed_at = _article(db_manager).published_at
    second_deploy = apply_publish_complete(deploy_event, db_manager)

    current = _article(db_manager)
    assert first_deploy["updated"] == 1
    assert second_deploy["updated"] == 0
    assert second_deploy["duplicates"] == 1
    assert second_deploy["conflicts"] == 0
    assert second_deploy["needs_attention"] is False
    assert current.processing_status == "completed"
    assert current.published_at == completed_at
    assert current.published_url == DEPLOY_URL
    assert _attempts(db_manager, article_id)[0].state == "REJECTED"
    assert _attempts(db_manager, article_id)[1].state == "COMPLETED"
    assert _event_types(db_manager, deployed_attempt.id).count("deployed") == 1


def test_ambiguous_identical_artifact_attempts_are_observable_noops(
    db_manager: DatabaseManager,
):
    article_id = int(_article(db_manager).id)
    first, first_ref = _start_attempt(
        db_manager,
        article_id,
        pull_request_number=111,
        content=b"identical PR artifact",
    )
    second, second_ref = _start_attempt(
        db_manager,
        article_id,
        pull_request_number=111,
        content=b"identical PR artifact",
    )

    result = apply_publish_complete(_deploy([first_ref]), db_manager)

    current = _article(db_manager)
    attempts = _attempts(db_manager, article_id)
    assert result["updated"] == 0
    assert result["needs_attention"] is True
    assert result["outcomes"][0]["reason"] == "ambiguous_attempt_reference"
    assert [attempt.state for attempt in attempts] == ["PR_CREATED", "PR_CREATED"]
    assert current.processing_status == "publishing"
    assert current.published_at is None
    assert current.published_url is None
    assert _event_types(db_manager, first.id) == ["pr_created"]
    assert _event_types(db_manager, second.id) == ["pr_created"]


def test_unmatched_callback_for_unknown_article_is_observable_noop(
    db_manager: DatabaseManager,
):
    unknown_id = "article-with-no-local-attempt"
    ref = {
        "refinery_id": unknown_id,
        "pull_request_number": 112,
        "content_sha256": hashlib.sha256(b"orphan callback").hexdigest(),
    }
    result = apply_publish_complete(
        _deploy([ref], publication_ids=[unknown_id]), db_manager
    )

    current = _article(db_manager)
    assert result["updated"] == 0
    assert result["needs_attention"] is True
    assert result["unmatched"] == 1
    assert result["outcomes"][0]["reason"] == "attempt_not_found"
    assert current.processing_status == "pending"
    assert current.published_at is None
    assert current.published_url is None
    assert (
        db_manager.lifecycle.get_publication_attempts_for_article(int(current.id)) == []
    )


def test_callback_missing_attempt_refs_does_not_speculate(db_manager: DatabaseManager):
    article_id = int(_article(db_manager).id)
    attempt, _ref = _start_attempt(
        db_manager,
        article_id,
        pull_request_number=113,
        content=b"legacy callback cannot identify this attempt",
    )

    legacy_event = _deploy([], publication_ids=[REFINERY_ID])
    result = apply_publish_complete(legacy_event, db_manager)

    current = _article(db_manager)
    lifecycle_attempt = _attempts(db_manager, article_id)[0]
    assert result["updated"] == 0
    assert result["needs_attention"] is True
    assert result["reason"] == "missing_publication_attempt_refs"
    assert lifecycle_attempt.state == "PR_CREATED"
    assert current.processing_status == "publishing"
    assert current.published_at is None
    assert current.published_url is None
    assert _event_types(db_manager, attempt.id) == ["pr_created"]
