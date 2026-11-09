"""Plan 212: the evidence gate sits on every path to the frontend."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from news_collector.contracts.adapters import strip_lifecycle_metadata
from news_collector.contracts.collector import CollectorArticleModel
from news_collector.editorial.evidence_gate import (
    GATE_ERROR_CODE,
    EvidenceGateDecision,
    UnsupportedSpecific,
)
from news_collector.logic.workflows.refinery_engine import RefineryEngine
from news_collector.logic.workflows.target_repo_publication import PublicationOutcome
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article
from news_collector.storage.publication_checkpoint_repository import (
    PublicationCheckpointRepository,
)
from tests.fixtures.images import raster_bytes
from tests.unit.editorial.test_editorial_draft import BODY, pipeline_agent

ENGINE_MODULE = "news_collector.logic.workflows.refinery_engine"
_LONG_SOURCE = (
    "Researchers analysed hair samples from eight mummies and detected cocaine. " * 30
)


def _engine() -> RefineryEngine:
    engine = RefineryEngine.__new__(RefineryEngine)
    engine._last_blocked_error = None
    return engine


def _run() -> MagicMock:
    return MagicMock()


def test_gate_blocks_and_records_the_reason_before_any_publication():
    engine, run = _engine(), _run()
    article = {"id": "9", "title": "t", "content": _LONG_SOURCE}
    draft = "---\ntitle: x\n---\n\nEl DMT y la técnica LC-MS/MS se usaron aquí.\n"

    assert engine._enforce_evidence_gate(article, draft, run) is False

    name, success = run.record_stage.call_args.args[:2]
    assert (name, success) == ("evidence_gate", False)
    details = run.record_stage.call_args.kwargs
    assert details["blocked"] is True and details["unsupported_count"] == 2
    run.persist_attempt.assert_called_once_with(False)
    assert engine._last_blocked_error["error_code"] == GATE_ERROR_CODE
    assert "DMT" in engine._last_blocked_error["message"]


def test_gate_lets_a_faithful_draft_through_and_records_success():
    engine, run = _engine(), _run()
    article = {"id": "9", "title": "t", "content": _LONG_SOURCE}
    draft = "---\ntitle: x\n---\n\nSe detectó cocaína en ocho momias.\n"

    assert engine._enforce_evidence_gate(article, draft, run) is True

    assert run.record_stage.call_args.args[:2] == ("evidence_gate", True)
    run.persist_attempt.assert_not_called()
    assert engine._last_blocked_error is None


def test_gate_fails_closed_when_the_checker_itself_breaks(monkeypatch):
    engine, run = _engine(), _run()

    def boom(*_args, **_kwargs):
        raise RuntimeError("checker defect")

    monkeypatch.setattr(f"{ENGINE_MODULE}.evaluate_evidence_gate", boom)

    assert engine._enforce_evidence_gate({"id": "9"}, "texto", run) is False

    assert run.record_stage.call_args.args[:2] == ("evidence_gate", False)
    assert run.record_stage.call_args.kwargs["reason"] == "checker_error"
    run.persist_attempt.assert_called_once_with(False)
    assert engine._last_blocked_error["error_code"] == GATE_ERROR_CODE


def test_gate_ignores_non_string_content_from_mock_editors():
    engine, run = _engine(), _run()
    assert engine._enforce_evidence_gate({"id": "9"}, None, run) is True
    run.record_stage.assert_not_called()


def _validate_source(payload):
    return CollectorArticleModel.model_validate(
        strip_lifecycle_metadata(payload)
    ).model_dump()


def test_resumed_checkpoint_draft_is_gated_before_publication(tmp_path, monkeypatch):
    """A sealed draft reused after the image wait skips the editor, so the gate
    must run on the resumed path too, before the target-repo workflow."""
    db = DatabaseManager({"type": "sqlite", "path": tmp_path / "gate.db"})
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
    config = SimpleNamespace(
        app=SimpleNamespace(
            editorial_mode="standard", policy_integrity_mode="disabled"
        ),
        paths={"data_dir": str(tmp_path)},
        github=SimpleNamespace(target_repo_url="https://example.org/site"),
    )
    monkeypatch.setattr(
        f"{ENGINE_MODULE}.EditorialAuditor",
        lambda cfg: SimpleNamespace(
            get_cached_score=lambda _: None, should_run_fast=lambda *a: False
        ),
    )
    target = tmp_path / "site"
    (target / "src/content/posts").mkdir(parents=True)

    def build_engine(agent):
        return RefineryEngine(
            db,
            MagicMock(),
            agent,
            config,
            contract_validator=_validate_source,
            checkpoint_run_id=run_id,
            checkpoint_repository=repo,
        )

    agent, _calls = pipeline_agent(tmp_path, monkeypatch)
    engine = build_engine(agent)
    try:
        first = engine.process_articles([article], MagicMock(), target)
        assert first["waiting_for_image_count"] == 1
        checkpoint = repo.load(run_id, "3822")
        assert checkpoint.status == "waiting_for_image"
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

        blocked = EvidenceGateDecision(
            blocked=True,
            threshold=2,
            source_chars=len(BODY),
            short_source=False,
            unsupported=(
                UnsupportedSpecific("acronym", "DMT", "body"),
                UnsupportedSpecific("acronym", "IMAO", "body"),
            ),
        )
        monkeypatch.setattr(
            f"{ENGINE_MODULE}.evaluate_evidence_gate", lambda *a, **k: blocked
        )
        agent2, calls2 = pipeline_agent(tmp_path, monkeypatch)
        engine = build_engine(agent2)
        published = []

        class Publisher:
            def publish(self, request, deps, record_stage):
                published.append(request.refined_content)
                return PublicationOutcome(success=True, pr_url="https://x/pr/1")

        engine.publication_workflow = Publisher()
        replay = engine.process_articles([checkpoint.article], MagicMock(), target)

        assert calls2 == []  # resumed: the editor did not run again
        assert published == []  # ...and nothing reached the publication workflow
        assert replay["processed_count"] == 0
        assert replay["errors"][0]["error_code"] == GATE_ERROR_CODE
    finally:
        engine.close()
