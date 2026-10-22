"""Image-brief provenance round-trip (plan 169).

The origin is recorded at upload time and must survive persistence, legacy
sidecars (no field) and rebuilds. Unknown values are rejected before any
asset is written.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from news_collector.contracts.image_brief import ImageBriefModel
from news_collector.logic.workflows.image_briefs import ImageBriefStore
from tests.fixtures.images import raster_bytes

PNG_BYTES = raster_bytes()


def _brief(slug: str = "brief-origin", **overrides) -> ImageBriefModel:
    values = {
        "slug": slug,
        "article_id": "123",
        "reason": "missing_source_image",
        "topic": "salud",
        "news_angle": "nuevo hallazgo",
        "scientific_domain": "medicina",
        "subject_scene": "laboratorio",
        "tone": "informativo",
        "draft_alt_text": "Laboratorio moderno con muestras",
        "generated_prompt": "Genera una imagen de un laboratorio moderno con un hallazgo medico.",
        "updated_at": datetime.now(timezone.utc),
    }
    values.update(overrides)
    return ImageBriefModel(**values)


def test_default_origin_is_unknown() -> None:
    assert _brief().image_origin == "unknown"


def test_brief_origin_round_trips_through_disk(tmp_path: Path) -> None:
    store = ImageBriefStore(tmp_path)
    store.save_brief(_brief(image_origin="ai_generated"))

    reloaded = store.load_brief("brief-origin")

    assert reloaded is not None
    assert reloaded.image_origin == "ai_generated"


def test_legacy_sidecar_without_origin_loads_as_unknown(tmp_path: Path) -> None:
    store = ImageBriefStore(tmp_path)
    payload = json.loads(_brief().model_dump_json())
    payload.pop("image_origin")
    store.brief_path("brief-origin").write_text(json.dumps(payload), encoding="utf-8")

    reloaded = store.load_brief("brief-origin")

    assert reloaded is not None
    assert reloaded.image_origin == "unknown"


def test_invalid_origin_is_rejected_by_the_contract() -> None:
    with pytest.raises(ValidationError):
        _brief(image_origin="scraped")


def test_stage_upload_persists_origin_and_preserves_it_on_reupload(
    tmp_path: Path,
) -> None:
    store = ImageBriefStore(tmp_path)
    store.save_brief(_brief())

    staged = store.stage_upload(
        brief=_brief(),
        filename="hero.png",
        content=PNG_BYTES,
        draft_alt_text="Laboratorio moderno con muestras",
        topic="salud",
        news_angle="nuevo hallazgo",
        scientific_domain="medicina",
        subject_scene="laboratorio",
        image_origin="ai_generated",
    )
    assert staged.image_origin == "ai_generated"
    assert store.load_brief("brief-origin").image_origin == "ai_generated"

    reuploaded = store.stage_upload(
        brief=staged,
        filename="hero.png",
        content=PNG_BYTES,
        draft_alt_text=staged.draft_alt_text,
        topic=staged.topic,
        news_angle=staged.news_angle,
        scientific_domain=staged.scientific_domain,
        subject_scene=staged.subject_scene,
    )
    assert reuploaded.image_origin == "ai_generated"


def test_stage_upload_rejects_unknown_origin_before_writing(tmp_path: Path) -> None:
    store = ImageBriefStore(tmp_path)
    store.save_brief(_brief())

    with pytest.raises(ValueError, match="Invalid image origin"):
        store.stage_upload(
            brief=_brief(),
            filename="hero.png",
            content=PNG_BYTES,
            draft_alt_text="Laboratorio moderno con muestras",
            topic="salud",
            news_angle="nuevo hallazgo",
            scientific_domain="medicina",
            subject_scene="laboratorio",
            image_origin="scraped",
        )

    assert not list(store.uploads_dir.glob("*"))


def test_rebuilding_a_brief_preserves_origin(tmp_path: Path) -> None:
    store = ImageBriefStore(tmp_path)
    existing = _brief(image_origin="licensed", uploaded_asset_path="/tmp/hero.png")

    rebuilt = store.build_brief(
        article={"id": "123", "title": "Título", "summary": "Resumen"},
        slug="brief-origin",
        reason="missing_source_image",
        existing=existing,
    )

    assert rebuilt.image_origin == "licensed"
