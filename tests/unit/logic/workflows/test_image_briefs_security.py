"""Boundary tests for the admin image-brief trust surface (plan 087).

Covers the NC-BE-087 S1 slug traversal guard and the S2 bounded,
type-checked upload staging on ImageBriefStore. API-level 413/422 cases
live next to the other image-brief serving tests in
tests/test_serving_admin_api.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from news_collector.contracts.image_brief import ImageBriefModel
from news_collector.logic.workflows.image_briefs import ImageBriefStore

TRAVERSAL_SLUGS = ["../x", "/abs", "a/b", "..", "", ".hidden", "-lead"]

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-png-body"
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"fake-jpeg-body"
GIF_BYTES = b"GIF89a" + b"fake-gif-body"
WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBP" + b"fake-webp-body"
AVIF_BYTES = b"\x00\x00\x00\x20ftypavif" + b"fake-avif-body"


def _make_store(tmp_path: Path) -> ImageBriefStore:
    return ImageBriefStore(tmp_path)


def _make_brief(slug: str) -> ImageBriefModel:
    return ImageBriefModel(
        slug=slug,
        article_id="123",
        reason="missing_source_image",
        topic="salud",
        news_angle="nuevo hallazgo",
        scientific_domain="medicina",
        subject_scene="laboratorio",
        tone="informativo",
        draft_alt_text="Imagen de laboratorio",
        generated_prompt="Genera una imagen de un laboratorio moderno con un hallazgo medico.",
        updated_at=datetime.now(timezone.utc),
    )


def _stage_kwargs(**overrides):
    kwargs = {
        "filename": "hero.png",
        "content": PNG_BYTES,
        "draft_alt_text": "Imagen de laboratorio",
        "topic": "salud",
        "news_angle": "nuevo hallazgo",
        "scientific_domain": "medicina",
        "subject_scene": "laboratorio",
    }
    kwargs.update(overrides)
    return kwargs


@pytest.mark.parametrize("slug", TRAVERSAL_SLUGS)
def test_brief_path_rejects_traversal_slugs(tmp_path: Path, slug: str) -> None:
    store = _make_store(tmp_path)
    with pytest.raises(ValueError):
        store.brief_path(slug)


@pytest.mark.parametrize("slug", TRAVERSAL_SLUGS)
def test_load_brief_rejects_traversal_slugs(tmp_path: Path, slug: str) -> None:
    store = _make_store(tmp_path)
    with pytest.raises(ValueError):
        store.load_brief(slug)


@pytest.mark.parametrize(
    ("title", "canonical_date"),
    [
        ("New AI blood test predicts stroke", "2026-05-22"),
        ("¡Avance médico! CRISPR & ARN: resultados", "2026-01-03"),
        ("Quantum dots — Nobel de Química 2026", "2026-09-16"),
    ],
)
def test_derive_slug_outputs_round_trip(
    tmp_path: Path, title: str, canonical_date: str
) -> None:
    """The guard must accept every slug the store itself produces."""
    store = _make_store(tmp_path)
    slug = store.derive_slug(
        article_id="abc", canonical_date=canonical_date, title=title
    )
    brief = _make_brief(slug)
    store.save_brief(brief)
    reloaded = store.load_brief(slug)
    assert reloaded is not None
    assert reloaded.slug == slug


@pytest.mark.parametrize(
    "filename", ["hero.svg", "page.html", "hero", "run.exe", "shell.php", "hero.SVG"]
)
def test_stage_upload_rejects_disallowed_extensions(
    tmp_path: Path, filename: str
) -> None:
    store = _make_store(tmp_path)
    brief = _make_brief("brief-ext-check")
    store.save_brief(brief)
    with pytest.raises(ValueError):
        store.stage_upload(brief=brief, **_stage_kwargs(filename=filename))


def test_stage_upload_accepts_png(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    brief = _make_brief("brief-png-ok")
    store.save_brief(brief)
    updated = store.stage_upload(brief=brief, **_stage_kwargs(filename="hero.png"))
    staged = Path(str(updated.uploaded_asset_path))
    assert staged.suffix == ".png"
    assert staged.read_bytes() == PNG_BYTES
    assert updated.status == "editorial_image_ready"


def test_stage_upload_normalizes_jpeg_extension(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    brief = _make_brief("brief-jpeg-norm")
    store.save_brief(brief)
    updated = store.stage_upload(
        brief=brief, **_stage_kwargs(filename="hero.jpeg", content=JPEG_BYTES)
    )
    assert Path(str(updated.uploaded_asset_path)).suffix == ".jpg"


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("hero.png", JPEG_BYTES),  # JPEG bytes labeled .png
        ("hero.jpg", PNG_BYTES),  # PNG bytes labeled .jpg
        ("hero.png", b"not an image at all"),
        ("hero.gif", GIF_BYTES.replace(b"GIF", b"XXX")),
        ("hero.webp", PNG_BYTES),
        ("hero.avif", JPEG_BYTES),
    ],
)
def test_stage_upload_rejects_magic_mismatch(
    tmp_path: Path, filename: str, content: bytes
) -> None:
    store = _make_store(tmp_path)
    brief = _make_brief("brief-magic-check")
    store.save_brief(brief)
    with pytest.raises(ValueError):
        store.stage_upload(
            brief=brief, **_stage_kwargs(filename=filename, content=content)
        )


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("hero.png", PNG_BYTES),
        ("hero.jpg", JPEG_BYTES),
        ("hero.gif", GIF_BYTES),
        ("hero.webp", WEBP_BYTES),
        ("hero.avif", AVIF_BYTES),
    ],
)
def test_stage_upload_accepts_genuine_types(
    tmp_path: Path, filename: str, content: bytes
) -> None:
    store = _make_store(tmp_path)
    brief = _make_brief("brief-genuine")
    store.save_brief(brief)
    updated = store.stage_upload(
        brief=brief, **_stage_kwargs(filename=filename, content=content)
    )
    assert Path(str(updated.uploaded_asset_path)).read_bytes() == content


def test_stage_upload_rejects_empty_content(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    brief = _make_brief("brief-empty")
    store.save_brief(brief)
    with pytest.raises(ValueError):
        store.stage_upload(brief=brief, **_stage_kwargs(content=b""))


def test_list_briefs_skips_invalid_stems(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.save_brief(_make_brief("brief-valid"))
    # Stray file whose stem cannot be a valid slug must not break listing.
    (store.briefs_dir / "bad slug.json").write_text("{}", encoding="utf-8")
    slugs = [brief.slug for brief in store.list_briefs()]
    assert slugs == ["brief-valid"]


def test_materialize_uses_constrained_extension(tmp_path: Path) -> None:
    """Staged extensions come from the allowlist, so materialize needs no change."""
    store = _make_store(tmp_path)
    brief = _make_brief("brief-materialize")
    store.save_brief(brief)
    updated = store.stage_upload(brief=brief, **_stage_kwargs(filename="hero.png"))
    target_dir = tmp_path / "assets"
    rel = store.materialize_uploaded_asset(brief=updated, target_assets_dir=target_dir)
    assert rel is not None
    assert rel.endswith(".png")
    assert (target_dir / "brief-materialize.png").exists()
