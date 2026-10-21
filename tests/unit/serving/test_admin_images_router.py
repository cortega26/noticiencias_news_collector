"""Hermetic unit cover for the extracted admin images router (plan 177).

``tests/test_serving_admin_api.py`` characterizes the same routes, but that
module is marked ``e2e`` and is deselected from the unit profile — so the
changed-file coverage ratchet would see ``serving/admin_images.py`` as almost
untouched. These tests exercise the router directly with a throwaway
``ImageBriefStore`` and no database, mirroring the e2e assertions without the
full app. Same precedent as ``test_write_surface_bounds.py``.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.testclient import TestClient

from news_collector.contracts.image_brief import ImageBriefModel
from news_collector.logic.workflows import image_briefs
from news_collector.serving import admin_images
from tests.fixtures.images import raster_bytes


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


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Route-level ``ImageBriefStore`` bound to a throwaway directory."""
    instance = image_briefs.ImageBriefStore(tmp_path)
    monkeypatch.setattr(image_briefs, "ImageBriefStore", lambda *a: instance)
    return instance


@pytest.fixture()
def client() -> TestClient:
    """Minimal app: only the images router, auth replaced by a no-op."""
    app = FastAPI()
    app.include_router(admin_images.build_router(lambda: None))
    return TestClient(app)


def test_queue_lists_briefs(client: TestClient, store) -> None:
    store.save_brief(_make_brief("brief-queue"))

    response = client.get("/v1/admin/images")
    assert response.status_code == 200
    briefs = response.json()["briefs"]
    assert [brief["slug"] for brief in briefs] == ["brief-queue"]
    assert briefs[0]["topic"] == "salud"


def test_update_roundtrip(client: TestClient, store) -> None:
    store.save_brief(_make_brief("brief-update"))

    response = client.put(
        "/v1/admin/images/brief-update",
        json={"topic": "nuevo tema", "image_origin": "licensed"},
    )
    assert response.status_code == 200
    assert response.json()["brief"]["topic"] == "nuevo tema"
    assert response.json()["brief"]["image_origin"] == "licensed"

    reloaded = store.load_brief("brief-update")
    assert reloaded.topic == "nuevo tema"
    assert reloaded.image_origin == "licensed"


def test_update_unknown_404(client: TestClient, store) -> None:
    response = client.put("/v1/admin/images/nope", json={"topic": "x"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Brief not found"


def test_update_empty_payload_422(client: TestClient, store) -> None:
    store.save_brief(_make_brief("brief-empty"))

    response = client.put("/v1/admin/images/brief-empty", json={})
    assert response.status_code == 422
    assert response.json()["detail"] == "No editable fields provided"


def test_update_traversal_slug_422(client: TestClient, store) -> None:
    response = client.put("/v1/admin/images/.hidden", json={"topic": "x"})
    assert response.status_code == 422


def test_upload_stages_asset(client: TestClient, store) -> None:
    store.save_brief(_make_brief("brief-upload"))

    response = client.post(
        "/v1/admin/images/brief-upload/upload",
        files={"file": ("hero.png", raster_bytes(), "image/png")},
        data={
            "draft_alt_text": "Imagen de laboratorio",
            "image_origin": "ai_generated",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["brief"]["status"] == "editorial_image_ready"
    assert body["brief"]["image_origin"] == "ai_generated"
    assert body["asset_path"].endswith(".png")


def test_upload_unknown_404(client: TestClient, store) -> None:
    response = client.post(
        "/v1/admin/images/nope/upload",
        files={"file": ("hero.png", raster_bytes(), "image/png")},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Brief not found"


def test_upload_traversal_slug_422(client: TestClient, store) -> None:
    response = client.post(
        "/v1/admin/images/.hidden/upload",
        files={"file": ("hero.png", raster_bytes(), "image/png")},
    )
    assert response.status_code == 422


def test_upload_empty_file_422(client: TestClient, store) -> None:
    store.save_brief(_make_brief("brief-empty-upload"))

    response = client.post(
        "/v1/admin/images/brief-empty-upload/upload",
        files={"file": ("hero.png", b"", "image/png")},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Empty file upload"


def test_upload_declared_length_over_cap_413(
    client: TestClient, store, monkeypatch
) -> None:
    store.save_brief(_make_brief("brief-big"))
    monkeypatch.setattr(admin_images, "MAX_UPLOAD_BYTES", 16)

    response = client.post(
        "/v1/admin/images/brief-big/upload",
        files={"file": ("hero.png", b"\x89PNG\r\n\x1a\n0123456789", "image/png")},
    )
    assert response.status_code == 413
    assert response.json()["detail"] == "File upload too large"


def test_upload_rejects_bad_type_422(client: TestClient, store) -> None:
    store.save_brief(_make_brief("brief-badtype"))

    response = client.post(
        "/v1/admin/images/brief-badtype/upload",
        files={"file": ("hero.svg", raster_bytes(), "image/svg+xml")},
    )
    assert response.status_code == 422


def test_read_upload_capped_rejects_over_cap() -> None:
    """Direct cover for the chunked-read 413 branch."""
    from fastapi import UploadFile

    small = UploadFile(file=io.BytesIO(b"abc"), filename="hero.png")
    assert admin_images._read_upload_capped(small, cap_bytes=16) == b"abc"

    big = UploadFile(
        file=io.BytesIO(b"\x89PNG\r\n\x1a\n0123456789"), filename="hero.png"
    )
    with pytest.raises(HTTPException) as exc_info:
        admin_images._read_upload_capped(big, cap_bytes=16)
    assert exc_info.value.status_code == 413


def test_verified_upload_notifies_after_durable_stage(store) -> None:
    store.save_brief(_make_brief("brief-resume"))
    ready_states = []

    def resume():
        ready_states.append(store.ready_for_article("123"))

    app = FastAPI()
    app.include_router(admin_images.build_router(lambda: None, resume))
    with TestClient(app) as client:
        response = client.post(
            "/v1/admin/images/brief-resume/upload",
            files={"file": ("hero.png", raster_bytes(), "image/png")},
            data={"image_origin": "ai_generated"},
        )
    assert response.status_code == 200
    assert ready_states == [True]


def test_unknown_upload_does_not_notify_until_rights_confirmed(store) -> None:
    store.save_brief(_make_brief("brief-rights"))
    notifications = []
    app = FastAPI()
    app.include_router(
        admin_images.build_router(lambda: None, lambda: notifications.append(True))
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/admin/images/brief-rights/upload",
            files={"file": ("hero.png", raster_bytes(), "image/png")},
        )
        assert response.status_code == 200
        assert response.json()["brief"]["status"] == "needs_editorial_image"
        assert notifications == []
        response = client.put(
            "/v1/admin/images/brief-rights", json={"image_origin": "licensed"}
        )
    assert response.status_code == 200
    assert store.ready_for_article("123")
    assert notifications == [True]


def test_resume_error_does_not_fail_committed_upload(store) -> None:
    store.save_brief(_make_brief("brief-busy"))

    def busy():
        raise RuntimeError("publication slot busy")

    app = FastAPI()
    app.include_router(admin_images.build_router(lambda: None, busy))
    with TestClient(app) as client:
        response = client.post(
            "/v1/admin/images/brief-busy/upload",
            files={"file": ("hero.png", raster_bytes(), "image/png")},
            data={"image_origin": "original"},
        )
    assert response.status_code == 200
    assert store.ready_for_article("123")


def test_generation_evidence_upload_is_verified_and_returned(client, store) -> None:
    import hashlib
    import json

    store.save_brief(_make_brief("brief-evidence"))
    evidence = {
        "prompt": "Raíces e hifas bajo tierra",
        "tool": "imagegen",
        "sha256": hashlib.sha256(raster_bytes()).hexdigest(),
        "width": 24,
        "height": 16,
    }
    response = client.post(
        "/v1/admin/images/brief-evidence/upload",
        files={"file": ("hero.png", raster_bytes(), "image/png")},
        data={
            "image_origin": "ai_generated",
            "generation_metadata": json.dumps(evidence),
        },
    )
    assert response.status_code == 200
    assert response.json()["brief"]["generation_metadata"] == evidence
    evidence["width"] = 42
    response = client.post(
        "/v1/admin/images/brief-evidence/upload",
        files={"file": ("hero.png", raster_bytes(), "image/png")},
        data={
            "image_origin": "ai_generated",
            "generation_metadata": json.dumps(evidence),
        },
    )
    assert response.status_code == 422
    assert store.ready_for_article("123")
