"""Plan 190: image readiness requires rights and verified durable bytes."""

from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PIL import Image

from news_collector.contracts.image_brief import ImageBriefModel
from news_collector.logic.workflows.image_briefs import ImageBriefStore
from news_collector.logic.workflows.image_handler import ArticleImageHandler


def image_bytes(color="green"):
    stream = io.BytesIO()
    Image.new("RGB", (24, 16), color).save(stream, format="PNG")
    return stream.getvalue()


def make_brief():
    return ImageBriefModel(
        slug="pending-roots",
        article_id="3822",
        reason="missing_source_image",
        topic="Raíces y hongos",
        news_angle="Intercambio de nutrientes en el suelo",
        scientific_domain="ecología",
        subject_scene="Raíces entre hifas en el suelo",
        tone="científico",
        draft_alt_text="Raíces y red de hifas en el suelo",
        generated_prompt="Ilustración científica horizontal de raíces y redes de hifas en el suelo.",
        updated_at=datetime.now(timezone.utc),
    )


def stage(store, brief=None, **kwargs):
    brief = brief or make_brief()
    return store.stage_upload(
        brief=brief,
        filename="roots.png",
        content=kwargs.pop("content", image_bytes()),
        draft_alt_text=brief.draft_alt_text,
        topic=brief.topic,
        news_angle=brief.news_angle,
        scientific_domain=brief.scientific_domain,
        subject_scene=brief.subject_scene,
        **kwargs,
    )


@pytest.mark.parametrize("origin", [None, "unknown"])
def test_unproven_staged_asset_remains_pending(tmp_path, origin):
    store = ImageBriefStore(tmp_path)
    updated = stage(store, image_origin=origin)
    assert updated.status == "needs_editorial_image"
    assert not store.ready_for_article("3822")
    assert (
        store.materialize_uploaded_asset(
            brief=updated, target_assets_dir=tmp_path / "target"
        )
        is None
    )


@pytest.mark.parametrize("origin", ["ai_generated", "licensed", "original"])
def test_known_rights_and_actual_file_are_ready(tmp_path, origin):
    store = ImageBriefStore(tmp_path)
    updated = stage(store, image_origin=origin)
    assert store.ready_for_article("3822")
    assert updated.asset_sha256 == hashlib.sha256(image_bytes()).hexdigest()
    assert (updated.asset_width, updated.asset_height) == (24, 16)
    assert not store.ready_for_article("different-article")
    assert (
        store.materialize_uploaded_asset(
            brief=updated, target_assets_dir=tmp_path / "target"
        )
        == "~/assets/images/pending-roots.png"
    )


def test_tampered_or_deleted_file_cannot_release_wait(tmp_path):
    store = ImageBriefStore(tmp_path)
    updated = stage(store, image_origin="ai_generated")
    path = Path(updated.uploaded_asset_path)
    path.write_bytes(image_bytes("red"))
    assert not store.ready_for_article("3822")
    path.unlink()
    assert not store.ready_for_article("3822")


def test_header_only_corruption_is_rejected_before_writing(tmp_path):
    store = ImageBriefStore(tmp_path)
    with pytest.raises(ValueError, match="image"):
        stage(store, image_origin="ai_generated", content=b"\x89PNG\r\n\x1a\nfake")
    assert not list(store.uploads_dir.iterdir())
    assert not list(store.briefs_dir.iterdir())


def test_generation_metadata_verified_against_actual_file(tmp_path):
    from news_collector.contracts.image_brief import ImageGenerationMetadata

    store = ImageBriefStore(tmp_path)
    metadata = ImageGenerationMetadata(
        prompt="Raíces e hifas en el suelo",
        tool="imagegen",
        sha256=hashlib.sha256(image_bytes()).hexdigest(),
        width=24,
        height=16,
    )
    updated = stage(store, image_origin="ai_generated", generation_metadata=metadata)
    assert store.load_brief(updated.slug).generation_metadata == metadata
    with pytest.raises(ValueError, match="metadata"):
        stage(
            store,
            image_origin="ai_generated",
            generation_metadata=metadata.model_copy(update={"width": 25}),
        )
    assert store.ready_for_article("3822")


def test_failed_sidecar_commit_keeps_previously_committed_asset(tmp_path, monkeypatch):
    store = ImageBriefStore(tmp_path)
    before = stage(store, image_origin="licensed")

    def fail(_brief):
        raise OSError("disk full")

    monkeypatch.setattr(store, "save_brief", fail)
    with pytest.raises(OSError, match="disk full"):
        stage(store, before, image_origin="ai_generated", content=image_bytes("blue"))
    assert Path(before.uploaded_asset_path).read_bytes() == image_bytes()
    assert store.ready_for_article("3822")


def test_legacy_sidecar_readable_without_provenance_or_dimensions(tmp_path):
    store = ImageBriefStore(tmp_path)
    legacy = make_brief().model_dump(mode="json")
    legacy.pop("image_origin")
    store.brief_path("pending-roots").write_text(__import__("json").dumps(legacy))
    assert store.load_brief("pending-roots").image_origin == "unknown"
    assert not store.ready_for_article("3822")


def test_unproven_local_path_queues_image_task(tmp_path):
    store = ImageBriefStore(tmp_path / "data")
    result = ArticleImageHandler(store).resolve(
        article={
            "id": "3822",
            "title": "Raíces y hongos",
            "summary": "Intercambio de nutrientes",
            "image_url": "~/assets/images/arbitrary.png",
        },
        article_id="3822",
        canonical_date="2026-01-01",
        preferred_slug=None,
        target_dir=tmp_path / "frontend",
    )
    assert not result.resolved
    assert result.queued_brief
    assert result.reason == "unproven_image_rights"


def test_changed_asset_does_not_inherit_prior_rights(tmp_path):
    store = ImageBriefStore(tmp_path)
    approved = stage(store, image_origin="licensed")
    changed = stage(store, approved, content=image_bytes("red"))
    assert changed.image_origin == "unknown"
    assert not store.ready_for_article("3822")


def test_image_upload_rejects_decoded_pixel_limit(tmp_path, monkeypatch):
    from news_collector.logic.workflows import image_briefs

    monkeypatch.setattr(image_briefs, "MAX_IMAGE_PIXELS", 32)
    store = ImageBriefStore(tmp_path)
    with pytest.raises(ValueError, match="dimensions"):
        stage(store, image_origin="original")
    assert not list(store.uploads_dir.iterdir())


def test_image_upload_rejects_actual_byte_limit(tmp_path, monkeypatch):
    from news_collector.logic.workflows import image_briefs

    monkeypatch.setattr(image_briefs, "MAX_IMAGE_BYTES", 8)
    store = ImageBriefStore(tmp_path)
    with pytest.raises(ValueError, match="too large"):
        stage(store, image_origin="original")
    assert not list(store.uploads_dir.iterdir())


def test_read_only_readiness_never_creates_directories(tmp_path):
    root = tmp_path / "not-created"
    store = ImageBriefStore(root, read_only=True)
    assert not store.ready_for_article("3822")
    assert not root.exists()


def test_download_adapter_exception_becomes_pending_image(tmp_path):
    def fail(*_args):
        raise ConnectionError("connection reset")

    store = ImageBriefStore(tmp_path / "data")
    handler = ArticleImageHandler(
        store, remote_image_hosts=frozenset({"licensed.example"})
    )
    result = handler.resolve(
        article={
            "id": "3822",
            "title": "Raíces y hongos",
            "summary": "Intercambio de nutrientes",
            "image_url": "https://licensed.example/image.png",
        },
        article_id="3822",
        canonical_date="2026-01-01",
        preferred_slug=None,
        target_dir=tmp_path / "frontend",
        download_fn=fail,
    )
    assert result.queued_brief
    assert result.reason == "image_download_failed"
    assert not result.resolved


def test_materialization_rejects_tampered_asset_without_writing(tmp_path):
    store = ImageBriefStore(tmp_path / "data")
    approved = stage(store, image_origin="ai_generated")
    Path(approved.uploaded_asset_path).write_bytes(image_bytes("purple"))
    destination = tmp_path / "target"
    assert (
        store.materialize_uploaded_asset(brief=approved, target_assets_dir=destination)
        is None
    )
    assert not destination.exists()


def test_slug_candidate_cannot_reuse_another_articles_asset(tmp_path):
    store = ImageBriefStore(tmp_path / "data")
    approved = stage(store, image_origin="original")
    assert store.find_for_article("another-article", [approved.slug]) is None


def test_readiness_rejects_asset_outside_upload_directory(tmp_path):
    store = ImageBriefStore(tmp_path / "data")
    approved = stage(store, image_origin="licensed")
    external = tmp_path / "external.png"
    external.write_bytes(image_bytes())
    store.save_brief(approved.model_copy(update={"uploaded_asset_path": str(external)}))
    assert not store.ready_for_article("3822")


def test_checkpoint_slug_selects_its_own_brief(tmp_path):
    """Plan 201: a ready brief under another slug cannot release the wait."""
    store = ImageBriefStore(tmp_path)
    stage(store, image_origin="ai_generated")  # slug pending-roots, ready
    other = make_brief().model_copy(update={"slug": "pending-roots-v2"})
    stage(store, brief=other)  # same article, no proven rights
    assert store.ready_for_article("3822", "pending-roots")
    assert not store.ready_for_article("3822", "pending-roots-v2")
    assert not store.ready_for_article("3822", "missing-slug")
    assert not store.ready_for_article("9999", "pending-roots")
