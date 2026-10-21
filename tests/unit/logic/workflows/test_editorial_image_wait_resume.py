"""Actual engine + editor + SQLite wait/resume, only transport/publication fakes."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from news_collector.contracts.adapters import strip_lifecycle_metadata
from news_collector.contracts.collector import CollectorArticleModel
from news_collector.contracts.frontend_schema import AstroPost
from news_collector.logic.workflows.refinery_engine import RefineryEngine
from news_collector.logic.workflows.target_repo_publication import PublicationOutcome
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article
from news_collector.storage.publication_checkpoint_repository import (
    PublicationCheckpointRepository,
)
from tests.fixtures.images import raster_bytes
from tests.unit.editorial.test_editorial_draft import BODY, pipeline_agent


def _validate_source(payload):
    return CollectorArticleModel.model_validate(
        strip_lifecycle_metadata(payload)
    ).model_dump()


def test_real_editor_survives_image_wait_and_restarts_without_llm(
    tmp_path, monkeypatch
):
    db = DatabaseManager({"type": "sqlite", "path": tmp_path / "wait.db"})
    now = datetime.now(timezone.utc)
    article = {
        "id": 3822,
        "title": "How fungi help roots",
        "content": BODY,
        "summary": BODY[:300],
        "url": "https://example.org/fungi",
        "source_id": "test",
        "source_name": "Test",
        "category": "salud",
        "published_date": now,
        "image_url": None,
    }
    with db.get_session() as session:
        session.add(
            Article(
                id=3822,
                title=article["title"],
                url=article["url"],
                content=BODY,
                summary=article["summary"],
                source_id="test",
                source_name="Test",
                published_date=now,
                collected_date=now,
            )
        )
    repo = PublicationCheckpointRepository(db)
    run_id = repo.standalone(["3822"])
    agent, calls = pipeline_agent(tmp_path, monkeypatch)
    config = SimpleNamespace(
        app=SimpleNamespace(
            editorial_mode="standard", policy_integrity_mode="disabled"
        ),
        paths={"data_dir": str(tmp_path)},
        github=SimpleNamespace(target_repo_url="https://example.org/site"),
    )
    monkeypatch.setattr(
        "news_collector.logic.workflows.refinery_engine.EditorialAuditor",
        lambda cfg: SimpleNamespace(
            get_cached_score=lambda _: None, should_run_fast=lambda *a: False
        ),
    )
    target = tmp_path / "site"
    (target / "src/content/posts").mkdir(parents=True)
    engine = RefineryEngine(
        db,
        MagicMock(),
        agent,
        config,
        contract_validator=_validate_source,
        checkpoint_run_id=run_id,
        checkpoint_repository=repo,
    )
    try:
        result = engine.process_articles([article], MagicMock(), target)
        assert result["errors"] == []
        assert result["waiting_for_image_count"] == 1
        checkpoint = repo.load(run_id, "3822")
        assert checkpoint.status == "waiting_for_image"
        assert not list((target / "src/content/posts").glob("*.md"))
        assert calls
        call_count = len(calls)
        # Image upload is a separate dependency; no change to original source.
        brief = engine.image_briefs.find_for_article("3822", [])
        engine.image_briefs.stage_upload(
            brief=brief,
            filename="fungi.png",
            content=raster_bytes(),
            draft_alt_text="Raíces asociadas con una red de hifas en el suelo",
            topic=brief.topic,
            news_angle=brief.news_angle,
            scientific_domain=brief.scientific_domain,
            subject_scene=brief.subject_scene,
            image_origin="ai_generated",
        )
        engine.close()
        # New process/editor, preserved SQLite checkpoint; no export read needed.
        agent2, calls2 = pipeline_agent(tmp_path, monkeypatch)
        engine = RefineryEngine(
            db,
            MagicMock(),
            agent2,
            config,
            contract_validator=_validate_source,
            checkpoint_run_id=run_id,
            checkpoint_repository=repo,
        )
        published = []

        class Publisher:
            def publish(self, request, deps, record_stage):
                published.append(request.refined_content)
                record_stage("pr_created", True)
                return PublicationOutcome(
                    success=True, pr_url="https://example.org/pr/3822"
                )

        engine.publication_workflow = Publisher()
        replay = engine.process_articles([checkpoint.article], MagicMock(), target)
        assert replay["processed_count"] == 1, replay
        assert len(calls) == call_count and calls2 == []
        assert (
            repo.load(run_id, "3822").identity.final_slug
            == checkpoint.identity.final_slug
        )
        assert repo.load(run_id, "3822").status == "succeeded"
        metadata = yaml.safe_load(published[0].split("---", 2)[1])
        AstroPost.model_validate(metadata)
        assert metadata["image_alt"].count("Ilustración generada con IA:") == 1
        assert metadata["refinery_id"] == "3822"
    finally:
        engine.close()
        db.close()
