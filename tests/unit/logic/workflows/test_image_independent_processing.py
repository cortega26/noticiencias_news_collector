"""Plan 190: image wait is durable and releases the global publication slot."""

from datetime import datetime, timezone

import pytest

from news_collector.logic.workflows.publication_run_workflow import (
    PublicationRunWorkflow,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import WorkflowRun


@pytest.fixture
def manager(tmp_path):
    db = DatabaseManager({"type": "sqlite", "path": tmp_path / "wait.db"})
    yield db
    db.close()


def test_image_wait_is_a_run_outcome_not_a_failure(manager, tmp_path, monkeypatch):
    workflow = PublicationRunWorkflow(manager, data_dir=tmp_path)
    monkeypatch.setattr(workflow, "_dispatch", lambda *a, **k: None)
    run_id = workflow.start(article_id=3822).run_id

    def completed_editorial(**kwargs):
        from news_collector.contracts.editorial_draft import EditorialDraft
        from news_collector.contracts.publication_checkpoint import (
            CheckpointIdentity,
            PublicationCheckpoint,
        )

        checkpoint = PublicationCheckpoint(
            article_id="3822",
            article={"id": "3822", "title": "Roots and fungi"},
            draft=EditorialDraft(
                article_id="3822",
                content="Raíces asociadas con hongos.",
                frontmatter={
                    "title": "Raíces y hongos del suelo",
                    "excerpt": "La asociación entre las raíces y los hongos.",
                    "date": "2026-03-02",
                },
            ),
            identity=CheckpointIdentity(
                final_slug="2026-03-02-raices",
                canonical_date="2026-03-02",
                output_filename="2026-03-02-raices.md",
                is_new=True,
            ),
            fingerprint="a" * 64,
            status="waiting_for_image",
            image_reason="missing_source_image",
            image_brief_slug="fungi",
        )
        kwargs["checkpoint_repository"].save(kwargs["checkpoint_run_id"], checkpoint)
        return {
            "status": "waiting_for_image",
            "processed_count": 0,
            "editorial_completed_count": 1,
            "waiting_for_image_count": 1,
            "image_reason": "missing_source_image",
            "image_brief_slug": "fungi",
        }

    monkeypatch.setattr(
        "news_collector.logic.workflows.publication_pipeline.run_publication_pipeline",
        completed_editorial,
    )
    workflow._run(run_id, 3822, None)
    result = workflow.get_status(run_id)
    assert result.run_status == "waiting_for_image"
    assert result.error_code is None
    assert result.summary["editorial_completed_count"] == 1
    assert result.finished_at is None
    assert workflow.start(article_id=999).status == "started"


def test_waiting_status_is_publication_only(manager):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with manager.get_session() as session:
            session.add(
                WorkflowRun(
                    run_type="collection",
                    status="waiting_for_image",
                    started_at=datetime.now(timezone.utc),
                )
            )
            session.flush()
