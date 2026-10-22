"""Module role: Own the admin image-brief HTTP surface (plan 177 / plan 060
Phase 7 — the first bounded admin route router).

Owns:
- The three image-brief routes — ``GET /v1/admin/images``,
  ``PUT /v1/admin/images/{slug}`` and
  ``POST /v1/admin/images/{slug}/upload`` — with their original function
  names (operationIds), paths, response models, status codes, defaults and
  error details.
- The upload ceiling (``MAX_UPLOAD_BYTES``), its chunk size and the capped
  chunked reader. The ceiling is read at request time from this module so
  tests can monkeypatch ``admin_images.MAX_UPLOAD_BYTES``.

Does NOT own:
- Authentication: ``build_router`` receives ``verify_admin_token`` from
  ``serving/api.py``. The factory parameter is what keeps the two modules
  from importing each other.
- Brief storage semantics: every request delegates to
  ``logic/workflows/image_briefs.ImageBriefStore``.

Invariants:
- No wire change: the router is mounted by ``create_app`` at the position
  the routes used to occupy, and the operationIds stay the endpoints' names.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from news_collector.contracts.admin import (
    AdminImageBriefItem,
    AdminImageBriefUpdate,
    AdminImageBriefUploadResult,
    AdminImageQueueEnvelope,
)
from news_collector.contracts.image_brief import (
    ImageBriefModel,
    ImageGenerationMetadata,
    ImageOrigin,
)
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger("AdminImages")

# NC-BE-087 S2: ceiling for admin image-brief uploads — generous above any
# GUI-produced hero image. Overridable in tests via monkeypatch.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_UPLOAD_CHUNK_BYTES = 1024 * 1024


def _read_upload_capped(upload: UploadFile, *, cap_bytes: int) -> bytes:
    """Read an upload in chunks, rejecting bodies over *cap_bytes* (413)."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = upload.file.read(_UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > cap_bytes:
            raise HTTPException(status_code=413, detail="File upload too large")
        chunks.append(chunk)
    return b"".join(chunks)


def build_router(  # noqa: C901
    verify_admin_token: Callable[..., None],
    on_image_ready: Callable[[], object] | None = None,
    *,
    data_dir: Path | None = None,
) -> APIRouter:
    """Build the admin images router with the caller's auth dependency.

    ``verify_admin_token`` is injected rather than imported: ``api.py`` owns
    it and imports this module, so importing it back would be a cycle.
    """
    router = APIRouter()
    image_data_dir = Path(data_dir) if data_dir is not None else Path("data")

    def notify_image_ready(store, brief: ImageBriefModel) -> None:
        if on_image_ready is None or not store.brief_ready(brief):
            return
        try:
            on_image_ready()
        except Exception as exc:
            # The durable stage succeeded. Periodic reconciliation will retry;
            # a busy publication slot must not turn a valid upload into failure.
            logger.warning(
                "Image staged for article {}; resume deferred: {}",
                brief.article_id,
                exc,
            )

    @router.get("/v1/admin/images", response_model=AdminImageQueueEnvelope)
    def admin_image_queue(
        _: None = Depends(verify_admin_token),
    ) -> AdminImageQueueEnvelope:
        from news_collector.logic.workflows.image_briefs import ImageBriefStore

        store = ImageBriefStore(image_data_dir)
        briefs = store.list_briefs()
        return AdminImageQueueEnvelope(
            briefs=[
                AdminImageBriefItem(
                    slug=brief.slug,
                    article_id=brief.article_id,
                    status=brief.status,
                    reason=brief.reason,
                    topic=brief.topic,
                    news_angle=brief.news_angle,
                    scientific_domain=brief.scientific_domain,
                    subject_scene=brief.subject_scene,
                    draft_alt_text=brief.draft_alt_text,
                    tone=brief.tone,
                    updated_at=(
                        brief.updated_at.isoformat()
                        if getattr(brief, "updated_at", None)
                        else None
                    ),
                    generated_prompt=brief.generated_prompt,
                    image_origin=brief.image_origin,
                    generation_metadata=brief.generation_metadata,
                    asset_sha256=brief.asset_sha256,
                    asset_width=brief.asset_width,
                    asset_height=brief.asset_height,
                )
                for brief in briefs
            ]
        )

    @router.put(
        "/v1/admin/images/{slug}",
        response_model=AdminImageBriefUploadResult,
    )
    def admin_update_image_brief(
        slug: str,
        payload: AdminImageBriefUpdate,
        _: None = Depends(verify_admin_token),
    ) -> AdminImageBriefUploadResult:
        """Edit an image brief's editable fields (no asset upload)."""
        from news_collector.logic.workflows.image_briefs import ImageBriefStore

        store = ImageBriefStore(image_data_dir)
        try:
            brief = store.load_brief(slug)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if brief is None:
            raise HTTPException(status_code=404, detail="Brief not found")

        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=422, detail="No editable fields provided")
        updated = brief.model_copy(
            update={**updates, "updated_at": datetime.now(timezone.utc)}
        )
        try:
            updated = store.update_brief(updated)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        notify_image_ready(store, updated)
        return AdminImageBriefUploadResult(
            brief=updated.model_dump(mode="json"),
            asset_path=updated.uploaded_asset_path or "",
        )

    @router.post(
        "/v1/admin/images/{slug}/upload",
        response_model=AdminImageBriefUploadResult,
    )
    def admin_upload_image_brief(
        slug: str,
        request: Request,
        file: UploadFile = File(...),
        topic: Optional[str] = Form(None),
        news_angle: Optional[str] = Form(None),
        scientific_domain: Optional[str] = Form(None),
        subject_scene: Optional[str] = Form(None),
        draft_alt_text: Optional[str] = Form(None),
        image_origin: Optional[ImageOrigin] = Form(None),
        generation_metadata: Optional[str] = Form(None),
        _: None = Depends(verify_admin_token),
    ) -> AdminImageBriefUploadResult:
        """Stage an image asset for a brief (multipart)."""
        from news_collector.logic.workflows.image_briefs import ImageBriefStore

        # NC-BE-087 S2: early reject when the declared body already exceeds
        # the cap, before touching the store or reading the stream.
        declared_length = request.headers.get("content-length")
        if (
            declared_length
            and declared_length.isdigit()
            and int(declared_length) > MAX_UPLOAD_BYTES
        ):
            raise HTTPException(status_code=413, detail="File upload too large")

        store = ImageBriefStore(image_data_dir)
        try:
            brief = store.load_brief(slug)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if brief is None:
            raise HTTPException(status_code=404, detail="Brief not found")

        content = _read_upload_capped(file, cap_bytes=MAX_UPLOAD_BYTES)
        if not content:
            raise HTTPException(status_code=422, detail="Empty file upload")
        try:
            updated = store.stage_upload(
                brief=brief,
                filename=file.filename or f"{slug}.png",
                content=content,
                draft_alt_text=draft_alt_text or brief.draft_alt_text,
                topic=topic or brief.topic,
                news_angle=news_angle or brief.news_angle,
                scientific_domain=scientific_domain or brief.scientific_domain,
                subject_scene=subject_scene or brief.subject_scene,
                image_origin=image_origin,
                generation_metadata=(
                    ImageGenerationMetadata.model_validate_json(generation_metadata)
                    if generation_metadata
                    else None
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        notify_image_ready(store, updated)
        return AdminImageBriefUploadResult(
            brief=updated.model_dump(mode="json"),
            asset_path=updated.uploaded_asset_path or "",
        )

    return router
