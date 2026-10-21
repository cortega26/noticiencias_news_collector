"""Durable image waits must retain drafts and ownership across restarts."""

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from runpy import run_path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from news_collector.contracts.editorial_draft import EditorialDraft
from news_collector.contracts.publication_checkpoint import (
    CheckpointIdentity,
    PublicationCheckpoint,
    PublicationItemOutcome,
)
from news_collector.logic.workflows.publication_run_workflow import (
    PublicationRunWorkflow,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article, WorkflowRun
from news_collector.storage.publication_checkpoint_repository import (
    PublicationCheckpointRepository,
)


@pytest.fixture
def manager(tmp_path):
    db = DatabaseManager({"type": "sqlite", "path": tmp_path / "checkpoint.db"})
    yield db
    db.close()


def parked_request(manager, *, started_at=None):
    started_at = started_at or datetime.now(timezone.utc)
    with manager.get_session() as session:
        run = WorkflowRun(
            run_type="publication",
            status="running",
            started_at=started_at,
            run_metadata={"article_id": 3822, "article_url": None},
        )
        session.add(run)
        session.flush()
        run_id = int(run.id)
    repository = PublicationCheckpointRepository(manager)
    draft = EditorialDraft(
        article_id="3822",
        content="Las raíces intercambian nutrientes con los hongos del suelo.",
        frontmatter={
            "title": "Raíces y hongos intercambian nutrientes",
            "excerpt": "Un estudio explora las relaciones entre raíces y hongos.",
            "date": "2026-03-02",
            "refinery_id": "3822",
        },
    )
    checkpoint = PublicationCheckpoint(
        article_id="3822",
        article={"id": "3822", "title": "Roots and fungi", "content": draft.content},
        draft=draft,
        identity=CheckpointIdentity(
            final_slug="2026-03-02-raices",
            canonical_date="2026-03-02",
            output_filename="2026-03-02-raices.md",
            is_new=True,
        ),
        fingerprint="a" * 64,
        status="waiting_for_image",
        image_reason="missing_source_image",
    )
    repository.save(run_id, checkpoint)
    assert repository.park(run_id, {"waiting_for_image_count": 1})
    return run_id, checkpoint


def test_checkpoint_survives_new_repository_and_duplicate_claim(manager):
    run_id, checkpoint = parked_request(manager)
    repository = PublicationCheckpointRepository(manager)
    restored = repository.load(run_id, "3822")
    assert restored == checkpoint
    restored.draft.assert_sealed()
    assert repository.claim(run_id)
    assert not repository.claim(run_id)
    assert repository.load(run_id, "3822").draft.content == checkpoint.draft.content


def test_old_image_wait_gets_fresh_lease_when_resumed(manager, tmp_path, monkeypatch):
    run_id, _ = parked_request(
        manager, started_at=datetime.now(timezone.utc) - timedelta(hours=2)
    )
    workflow = PublicationRunWorkflow(manager, data_dir=tmp_path)
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **kw: None)
    assert workflow._checkpoints.claim(run_id)
    assert workflow._transition(run_id, from_status="queued", to_status="running")

    # A second operator request must not reap the newly resumed owner merely
    # because its original request predates the ordinary one-hour lease.
    result = workflow.start(article_id=999)
    assert result.status == "already_running"
    assert result.run_id == run_id
    assert workflow.get_status(run_id).run_status == "running"


def test_crash_after_resume_claim_retains_recoverable_request(manager, tmp_path):
    run_id, checkpoint = parked_request(manager)
    repository = PublicationCheckpointRepository(manager)
    assert repository.claim(run_id)
    # The process dies after its durable claim, before a worker starts.
    restarted = PublicationRunWorkflow(manager, data_dir=tmp_path)
    restarted.recover_expired_leases()

    assert restarted.get_status(run_id).run_status == "waiting_for_image"
    assert restarted._checkpoints.load(run_id, "3822") == checkpoint
    assert [rid for rid, _ in restarted._checkpoints.waiting()] == [run_id]


def test_failed_sibling_outcome_survives_without_a_draft(manager):
    run_id, checkpoint = parked_request(manager)
    repository = PublicationCheckpointRepository(manager)
    assert repository.claim(run_id)
    workflow = PublicationRunWorkflow(manager)
    assert workflow._transition(run_id, from_status="queued", to_status="running")
    failed = PublicationItemOutcome(
        article_id="999",
        status="failed",
        error_code="E_EDITORIAL_VALUE_ADD",
        message="Editorial rejection before draft creation",
    )
    repository.save_outcome(run_id, failed)
    assert repository.outcomes(run_id) == {"999": failed}
    assert repository.load(run_id, "3822") == checkpoint
    assert repository.load(run_id, "999") is None


def test_busy_global_slot_leaves_request_claimable_later(
    manager, tmp_path, monkeypatch
):
    run_id, _ = parked_request(manager)
    workflow = PublicationRunWorkflow(manager, data_dir=tmp_path)
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **kw: None)
    active_id = workflow.start(article_id=999).run_id
    repository = PublicationCheckpointRepository(manager)
    assert not repository.claim(run_id)
    assert workflow.get_status(run_id).run_status == "waiting_for_image"
    assert workflow._transition(active_id, from_status="queued", to_status="running")
    assert workflow.complete(active_id, summary={})
    assert repository.claim(run_id)


def test_ready_checkpoint_recovery_redispatches_original_snapshot(
    manager, tmp_path, monkeypatch
):
    run_id, checkpoint = parked_request(manager)
    with manager.get_session() as session:
        row = session.get(WorkflowRun, run_id)
        row.run_metadata = {
            **row.run_metadata,
            "checkpoints": {
                "3822": checkpoint.model_copy(update={"status": "ready"}).model_dump(
                    mode="json"
                )
            },
        }
        row.status = "queued"
    workflow = PublicationRunWorkflow(manager, data_dir=tmp_path)
    dispatched = []
    monkeypatch.setattr(
        workflow, "_dispatch", lambda rid, **kw: dispatched.append((rid, kw))
    )
    workflow.recover_expired_leases()
    assert workflow.reconcile_waiting() == 1
    assert dispatched == [(run_id, {"article_id": 3822, "article_url": None})]
    assert workflow._checkpoints.load(run_id, "3822").article == checkpoint.article


def test_same_succeeded_revision_reuses_evidence_but_changed_source_starts_new_run(
    manager, tmp_path, monkeypatch
):
    run_id, checkpoint = parked_request(manager)
    with manager.get_session() as session:
        session.add(
            Article(
                id=3822,
                title=checkpoint.article["title"],
                content=checkpoint.article["content"],
                url="https://example.org/fungi",
                source_id="fixture",
                source_name="Fixture",
            )
        )
        row = session.get(WorkflowRun, run_id)
        row.run_metadata = {
            **row.run_metadata,
            "checkpoints": {
                "3822": checkpoint.model_copy(
                    update={"status": "succeeded", "pr_url": "https://example.org/pr/1"}
                ).model_dump(mode="json")
            },
        }
        row.status = "succeeded"
    workflow = PublicationRunWorkflow(manager, data_dir=tmp_path)
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **kw: None)
    repeated = workflow.start(article_id=3822)
    assert repeated.status == "existing"
    assert repeated.run_id == run_id
    with manager.get_session() as session:
        row = session.get(Article, 3822)
        row.article_metadata = {"image_url": "/images/new-image.webp"}
    assert workflow.start(article_id=3822).run_id == run_id
    with manager.get_session() as session:
        session.get(Article, 3822).content = (
            "Revised scientific results requiring new editorial work"
        )
    changed = workflow.start(article_id=3822)
    assert changed.status == "started"
    assert changed.run_id != run_id


def test_shutdown_prevents_new_dispatch_and_closed_db_does_not_escape(
    manager, tmp_path
):
    workflow = PublicationRunWorkflow(manager, data_dir=tmp_path)
    workflow.stop_reconciler()
    manager.close()
    assert workflow._reconcile_waiting_safely() == 0


def test_image_wait_migration_refuses_lossy_downgrade_and_preserves_drafts(manager):
    run_id, checkpoint = parked_request(manager)
    migration = run_path(
        str(
            Path(__file__).resolve().parents[3]
            / "alembic/versions/f190a1b2c3d4_publication_image_wait.py"
        )
    )
    with manager.engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(
                NotImplementedError, match="checkpoints must be preserved"
            ):
                migration["downgrade"]()
    assert PublicationCheckpointRepository(manager).load(run_id, "3822") == checkpoint
    with manager.get_session() as session:
        session.get(WorkflowRun, run_id).status = "interrupted"
    with manager.engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration["downgrade"]()
        previous = sa.inspect(connection).get_check_constraints("workflow_runs")
        assert all("waiting_for_image" not in check["sqltext"] for check in previous)
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()
            migration["upgrade"]()
    assert PublicationCheckpointRepository(manager).load(run_id, "3822") == checkpoint
    with manager.get_session() as session:
        session.get(WorkflowRun, run_id).status = "waiting_for_image"
    assert [rid for rid, _ in PublicationCheckpointRepository(manager).waiting()] == [
        run_id
    ]


def test_fresh_checkpoint_from_dead_process_recovers_without_hour_lease(
    manager, tmp_path
):
    run_id, checkpoint = parked_request(manager)
    exited = subprocess.Popen([sys.executable, "-c", "pass"])
    exited.wait(timeout=10)
    with manager.get_session() as session:
        row = session.get(WorkflowRun, run_id)
        row.status = "running"
        row.heartbeat_at = datetime.now(timezone.utc)
        row.run_metadata = {**row.run_metadata, "worker_pid": exited.pid}
    workflow = PublicationRunWorkflow(manager, data_dir=tmp_path)
    assert workflow.recover_expired_leases() == [run_id]
    assert workflow.get_status(run_id).run_status == "waiting_for_image"
    assert workflow._checkpoints.load(run_id, "3822") == checkpoint


@pytest.mark.parametrize("checkpoint_values", [{}, {"3822": {}}, []])
def test_damaged_wait_does_not_block_unrelated_ready_request(
    manager, tmp_path, monkeypatch, checkpoint_values
):
    bad_id, _ = parked_request(manager)
    with manager.get_session() as session:
        row = session.get(WorkflowRun, bad_id)
        row.run_metadata = {**row.run_metadata, "checkpoints": checkpoint_values}
    ready_id, checkpoint = parked_request(manager)
    with manager.get_session() as session:
        row = session.get(WorkflowRun, ready_id)
        row.run_metadata = {
            **row.run_metadata,
            "checkpoints": {
                "3822": checkpoint.model_copy(update={"status": "ready"}).model_dump(
                    mode="json"
                )
            },
        }
    workflow = PublicationRunWorkflow(manager, data_dir=tmp_path)
    dispatched = []
    monkeypatch.setattr(workflow, "_dispatch", lambda rid, **kw: dispatched.append(rid))
    assert workflow.reconcile_waiting() == 1
    assert dispatched == [ready_id]
    rejected = workflow.get_status(bad_id)
    assert rejected.run_status == "failed"
    assert rejected.error_code == "invalid_publication_checkpoint"
    with manager.get_session() as session:
        assert (
            session.get(WorkflowRun, bad_id).run_metadata["checkpoints"]
            == checkpoint_values
        )


@pytest.mark.parametrize("checkpoint_values", [{}, {"3822": {}}, []])
def test_damaged_wait_does_not_reuse_or_block_explicit_new_request(
    manager, tmp_path, monkeypatch, checkpoint_values
):
    bad_id, _ = parked_request(manager)
    with manager.get_session() as session:
        row = session.get(WorkflowRun, bad_id)
        row.run_metadata = {**row.run_metadata, "checkpoints": checkpoint_values}
    workflow = PublicationRunWorkflow(manager, data_dir=tmp_path)
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **kw: None)
    result = workflow.start(article_id=3822)
    assert result.status == "started"
    assert result.run_id != bad_id


def test_new_source_revision_does_not_rewrite_succeeded_sibling_checkpoint(
    manager, tmp_path, monkeypatch
):
    run_id, checkpoint = parked_request(manager)
    succeeded = checkpoint.model_copy(
        update={"status": "succeeded", "pr_url": "https://example.org/pr/1"}
    )
    waiting = checkpoint.model_copy(
        update={
            "article_id": "3823",
            "article": {**checkpoint.article, "id": "3823"},
            "draft": checkpoint.draft.model_copy(
                update={"article_id": "3823", "seal": ""}
            ),
        }
    )
    waiting = PublicationCheckpoint.model_validate(waiting.model_dump(mode="json"))
    with manager.get_session() as session:
        session.add(
            Article(
                id=3822,
                title=checkpoint.article["title"],
                content="A newly revised source",
                url="https://example.org/fungi",
                source_id="fixture",
                source_name="Fixture",
            )
        )
        row = session.get(WorkflowRun, run_id)
        row.run_metadata = {
            "mode": "batch",
            "article_ids": [3822, 3823],
            "checkpoints": {
                "3822": succeeded.model_dump(mode="json"),
                "3823": waiting.model_dump(mode="json"),
            },
        }
    workflow = PublicationRunWorkflow(manager, data_dir=tmp_path)
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **kw: None)
    assert workflow.start(article_id=3822).status == "started"
    repository = PublicationCheckpointRepository(manager)
    assert repository.load(run_id, "3822") == succeeded
    assert repository.load(run_id, "3823").status == "waiting_for_image"
    assert workflow.get_status(run_id).run_status == "waiting_for_image"


def test_concurrent_claims_dispatch_a_parked_request_only_once(manager):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    run_id, _ = parked_request(manager)
    ready = Barrier(2)

    def claim():
        ready.wait(timeout=5)
        return PublicationCheckpointRepository(manager).claim(run_id)

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: claim(), range(2)))
    assert sorted(results) == [False, True]


def test_busy_slot_rolls_back_source_supersession(manager, tmp_path, monkeypatch):
    old_id, checkpoint = parked_request(manager)
    with manager.get_session() as session:
        session.add(
            Article(
                id=3822,
                title=checkpoint.article["title"],
                content="Changed scientific results",
                url="https://example.org/fungi",
                source_id="fixture",
                source_name="Fixture",
            )
        )
    workflow = PublicationRunWorkflow(manager, data_dir=tmp_path)
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **kw: None)
    busy = workflow.start(article_id=999)
    assert busy.status == "started"
    conflict = workflow.start(article_id=3822)
    assert conflict.status == "already_running"
    assert conflict.run_id == busy.run_id
    assert workflow.get_status(old_id).run_status == "waiting_for_image"
    assert workflow._checkpoints.load(old_id, "3822") == checkpoint
    assert workflow._transition(busy.run_id, from_status="queued", to_status="running")
    assert workflow.complete(busy.run_id, summary={})
    accepted = workflow.start(article_id=3822)
    assert accepted.status == "started"
    assert accepted.run_id != old_id
    assert workflow.get_status(old_id).run_status == "cancelled"
    assert workflow.get_status(old_id).error_code == "source_revision_superseded"
    assert workflow._checkpoints.load(old_id, "3822").status == "failed"


def test_explicit_failed_sibling_retry_does_not_alias_parked_batch(
    manager, tmp_path, monkeypatch
):
    run_id, checkpoint = parked_request(manager)
    failure = PublicationItemOutcome(
        article_id="999", status="failed", error_code="E_EDITORIAL_VALUE_ADD"
    )
    with manager.get_session() as session:
        row = session.get(WorkflowRun, run_id)
        row.run_metadata = {
            **row.run_metadata,
            "mode": "batch",
            "article_ids": [3822, 999],
            "item_outcomes": {"999": failure.model_dump(mode="json")},
        }
    workflow = PublicationRunWorkflow(manager, data_dir=tmp_path)
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **kw: None)
    retry = workflow.start(article_id=999)
    assert retry.status == "started"
    assert retry.run_id != run_id
    assert workflow._checkpoints.outcomes(run_id) == {"999": failure}
    assert workflow._checkpoints.load(run_id, "3822") == checkpoint


def test_shutdown_during_image_readiness_keeps_request_parked(
    manager, tmp_path, monkeypatch
):
    from news_collector.logic.workflows.image_briefs import ImageBriefStore

    run_id, _ = parked_request(manager)
    workflow = PublicationRunWorkflow(manager, data_dir=tmp_path)
    dispatched = []

    def ready_then_stop(_store, _article_id):
        workflow.stop_reconciler()
        return True

    monkeypatch.setattr(ImageBriefStore, "ready_for_article", ready_then_stop)
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **kw: dispatched.append(a))
    assert workflow.reconcile_waiting() == 0
    assert dispatched == []
    assert workflow.get_status(run_id).run_status == "waiting_for_image"


def test_stopped_workflow_cannot_spawn_new_worker(manager, tmp_path):
    from threading import Event

    called = Event()
    workflow = PublicationRunWorkflow(manager, data_dir=tmp_path)
    workflow.stop_reconciler()
    workflow._spawn(target=called.set, args=(), name="stopped-publication")
    workflow.join_dispatched_threads()
    assert not called.is_set()


@pytest.mark.parametrize("as_batch", [False, True], ids=["single", "batch"])
def test_repeated_request_reuses_original_image_wait_without_dispatch(
    manager, tmp_path, monkeypatch, as_batch
):
    run_id, checkpoint = parked_request(manager)
    if as_batch:
        with manager.get_session() as session:
            row = session.get(WorkflowRun, run_id)
            row.run_metadata = {
                **row.run_metadata,
                "mode": "batch",
                "article_ids": [3822],
            }
    workflow = PublicationRunWorkflow(manager, data_dir=tmp_path)
    dispatched = []
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **kw: dispatched.append(a))
    monkeypatch.setattr(
        workflow, "_dispatch_batch", lambda *a, **kw: dispatched.append(a)
    )
    for _ in range(2):
        result = (
            workflow.start_batch([3822])
            if as_batch
            else workflow.start(article_id=3822)
        )
        assert result.status == "waiting_for_image"
        assert result.run_id == run_id
    assert dispatched == []
    assert workflow._checkpoints.load(run_id, "3822") == checkpoint
    with manager.get_session() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(WorkflowRun)) == 1


def test_completed_batch_reuses_recorded_pr_without_starting_new_run(
    manager, tmp_path, monkeypatch
):
    run_id, checkpoint = parked_request(manager)
    with manager.get_session() as session:
        session.add(
            Article(
                id=3822,
                title=checkpoint.article["title"],
                content=checkpoint.article["content"],
                url="https://example.org/fungi",
                source_id="fixture",
                source_name="Fixture",
            )
        )
        row = session.get(WorkflowRun, run_id)
        row.status = "succeeded"
        row.run_metadata = {
            **row.run_metadata,
            "mode": "batch",
            "article_ids": [3822],
            "checkpoints": {
                "3822": checkpoint.model_copy(
                    update={"status": "succeeded", "pr_url": "https://example.org/pr/1"}
                ).model_dump(mode="json")
            },
        }
    workflow = PublicationRunWorkflow(manager, data_dir=tmp_path)
    dispatched = []
    monkeypatch.setattr(
        workflow, "_dispatch_batch", lambda *a, **kw: dispatched.append(a)
    )
    result = workflow.start_batch([3822])
    assert result.status == "existing"
    assert result.run_id == run_id
    assert dispatched == []
    assert (
        workflow._checkpoints.load(run_id, "3822").pr_url == "https://example.org/pr/1"
    )
    with manager.get_session() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(WorkflowRun)) == 1


def test_reconciler_startup_resumes_checkpoint_once_and_stops_cleanly(
    manager, tmp_path, monkeypatch
):
    run_id, checkpoint = parked_request(manager)
    with manager.get_session() as session:
        row = session.get(WorkflowRun, run_id)
        row.run_metadata = {
            **row.run_metadata,
            "checkpoints": {
                "3822": checkpoint.model_copy(update={"status": "ready"}).model_dump(
                    mode="json"
                )
            },
        }
    workflow = PublicationRunWorkflow(manager, data_dir=tmp_path)
    calls = []

    def publish(**kwargs):
        calls.append(kwargs["process_id"])
        return {
            "status": "success",
            "processed_count": 1,
            "pr_url": "https://example.org/pr/1",
        }

    monkeypatch.setattr(
        "news_collector.logic.workflows.publication_pipeline.run_publication_pipeline",
        publish,
    )
    try:
        workflow.start_reconciler()
        workflow.start_reconciler()
        workflow.join_dispatched_threads(timeout=10)
        assert workflow.get_status(run_id).run_status == "succeeded"
        assert (
            workflow.get_status(run_id).summary["pr_url"] == "https://example.org/pr/1"
        )
        assert calls == ["3822"]
    finally:
        workflow.stop_reconciler()
    assert workflow.reconcile_waiting() == 0
