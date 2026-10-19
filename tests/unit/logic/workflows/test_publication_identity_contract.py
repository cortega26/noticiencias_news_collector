"""Behavioural contract tests for publication identity (plan 140).

Mutation testing (plan 140) showed these behaviours were reached but not
asserted: the per-item error contracts the batch reporter surfaces
(LAW-B6), the empty-id guard (LAW-B5), date-shape parsing, creation-mode
title slugs, collision bumps, and the atomic exclusive-create primitive.

All tests are behavioural: they assert deterministic public outputs
(slug/date/filename, ``error_code``/``public_message``, raised types and
attributes). No private helper is inspected directly and no production
code changed.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from news_collector.logic.workflows import publication_identity as identity_mod
from news_collector.logic.workflows.publication_identity import (
    EmptyArticleIdError,
    FinalizeSlugError,
    IdentityPersistenceError,
    PublicationIdentity,
    PublicationIdentityResolver,
    SlugCollisionError,
    UndatedArticleError,
    infer_manual_published_date,
)

# ---------------------------------------------------------------------------
# Stubs — record call arguments so the resolver's DB/manifest contract is
# asserted behaviourally (identity must be looked up by the caller's id).
# ---------------------------------------------------------------------------


class _RecordingDB:
    def __init__(self, slug: str | None = None, set_result: bool = True) -> None:
        self.slug = slug
        self.set_result = set_result
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, str]] = []

    def get_canonical_slug(self, article_id: str) -> str | None:
        self.get_calls.append(article_id)
        return self.slug

    def set_canonical_slug(self, article_id: str, slug: str) -> bool:
        self.set_calls.append((article_id, slug))
        return self.set_result


class _Manifest:
    def __init__(self, existing: Path | None = None) -> None:
        self.existing = existing
        self.calls: list[tuple[Path, str]] = []

    def find_existing_file(self, posts_dir: Path, article_id: str) -> Path | None:
        self.calls.append((posts_dir, article_id))
        return self.existing


def _resolver(db=None, manifest=None) -> PublicationIdentityResolver:
    if db is None:
        db = _RecordingDB()
    if manifest is None:
        manifest = _Manifest()
    return PublicationIdentityResolver(db=db, manifest=manifest)


# ---------------------------------------------------------------------------
# Per-item error contracts (error_code + public_message + message detail)
# ---------------------------------------------------------------------------


def test_undated_article_error_contract() -> None:
    err = UndatedArticleError("42", "published_date")
    assert err.error_code == "E_IDENTITY_NO_DATE"
    assert err.article_id == "42"
    assert err.field == "published_date"
    assert str(err) == (
        "Article '42' has no usable published_date for canonical publication "
        "identity — refusing to invent a non-deterministic date."
    )
    assert err.public_message == (
        "El artículo no tiene una fecha válida para publicar y el "
        "sistema no inventa fechas (identidad no determinista). "
        "Añade una fecha editorial o revisa los datos de origen."
    )


def test_undated_article_error_appends_detail() -> None:
    err = UndatedArticleError("7", "collected_date", detail="unparseable value 'x'")
    assert str(err).endswith(
        "refusing to invent a non-deterministic date. unparseable value 'x'"
    )


def test_empty_article_id_error_contract() -> None:
    err = EmptyArticleIdError()
    assert err.error_code == "E_IDENTITY_EMPTY_ID"
    assert err.article_id == ""
    assert str(err) == (
        "Empty article_id cannot yield deterministic publication identity — "
        "refusing to mint randomness."
    )
    assert err.public_message == (
        "El artículo no tiene un identificador válido para publicar y "
        "el sistema no inventa identificadores (identidad no "
        "determinista). Revisa los datos de origen."
    )


def test_empty_article_id_error_appends_detail() -> None:
    err = EmptyArticleIdError(detail="context")
    assert str(err).endswith("refusing to mint randomness. context")


def test_identity_persistence_error_contract() -> None:
    err = IdentityPersistenceError("5")
    assert err.error_code == "E_IDENTITY_PERSISTENCE"
    assert err.article_id == "5"
    assert str(err) == (
        "Failed to persist canonical slug for article '5' "
        "(DB outage or missing row)."
    )
    assert err.public_message == (
        "No se pudo guardar la identidad de publicación en la base de "
        "datos. El artículo no se publica hasta que la identidad quede "
        "bloqueada. Reintenta más tarde."
    )


def test_identity_persistence_error_appends_detail() -> None:
    err = IdentityPersistenceError("5", detail="outage")
    assert str(err).endswith("(DB outage or missing row). outage")


def test_slug_collision_error_contract() -> None:
    err = SlugCollisionError("5", "2024-01-01-x")
    assert err.error_code == "E_IDENTITY_SLUG_COLLISION"
    assert err.article_id == "5"
    assert err.slug == "2024-01-01-x"
    assert str(err) == (
        "Canonical slug '2024-01-01-x' for article '5' collides with a "
        "different article's locked identity."
    )
    assert err.public_message == (
        "El identificador de publicación choca con otro artículo ya "
        "publicado. El artículo no se publica para no sobrescribirlo. "
        "Revisa el título/fecha o elige un slug distinto."
    )


def test_slug_collision_error_appends_detail() -> None:
    err = SlugCollisionError("5", "2024-01-01-x", detail="owner=6")
    assert str(err).endswith("locked identity. owner=6")


def test_finalize_slug_error_contract() -> None:
    err = FinalizeSlugError()
    assert err.error_code == "E_IDENTITY_FINALIZE_NOT_NEW"
    assert str(err) == (
        "finalize_slug only valid for creation-mode identities (is_new=True)."
    )
    assert err.public_message == (
        "La identidad de publicación ya está bloqueada y no puede "
        "regenerarse. Reintenta la publicación desde el estado actual."
    )


def test_finalize_slug_error_appends_detail() -> None:
    err = FinalizeSlugError(detail="locked")
    assert str(err).endswith("(is_new=True). locked")


# ---------------------------------------------------------------------------
# Empty-id guard (LAW-B5): every entry point fails closed, never mints ids
# ---------------------------------------------------------------------------


def test_resolve_rejects_empty_article_id(tmp_path: Path) -> None:
    with pytest.raises(EmptyArticleIdError) as exc_info:
        _resolver().resolve(article_id="", article={}, posts_dir=tmp_path)
    assert exc_info.value.article_id == ""
    assert str(exc_info.value).endswith("refusing to mint randomness.")


def test_resolve_rejects_whitespace_article_id(tmp_path: Path) -> None:
    with pytest.raises(EmptyArticleIdError):
        _resolver().resolve(article_id="   ", article={}, posts_dir=tmp_path)


def test_resolve_rejects_none_article_id(tmp_path: Path) -> None:
    with pytest.raises(EmptyArticleIdError):
        _resolver().resolve(article_id=None, article={}, posts_dir=tmp_path)  # type: ignore[arg-type]


def test_finalize_slug_rejects_empty_article_id(tmp_path: Path) -> None:
    identity = PublicationIdentity(
        final_slug="2024-01-25-x",
        canonical_date="2024-01-25",
        output_filename="2024-01-25-x.md",
        is_new=True,
    )
    with pytest.raises(EmptyArticleIdError):
        _resolver().finalize_slug(identity, "title: X", "", tmp_path)


def test_register_slug_rejects_empty_article_id() -> None:
    with pytest.raises(EmptyArticleIdError):
        _resolver().register_slug("", "2024-01-01-x")


def test_backfill_slug_rejects_empty_article_id() -> None:
    db = _RecordingDB()
    assert _resolver(db=db).backfill_slug("", "2024-01-01-x") is False
    assert db.set_calls == []


# ---------------------------------------------------------------------------
# Persistence branches (backfill returns bool; register raises typed errors)
# ---------------------------------------------------------------------------


def test_backfill_slug_rejects_blank_slug() -> None:
    db = _RecordingDB()
    resolver = _resolver(db=db)
    assert resolver.backfill_slug("42", "") is False
    assert resolver.backfill_slug("42", "   ") is False
    assert db.set_calls == []


def test_backfill_slug_without_db_method_returns_false() -> None:
    assert _resolver(db=SimpleNamespace()).backfill_slug("42", "2024-01-01-x") is False


def test_register_slug_rejects_blank_slug() -> None:
    with pytest.raises(IdentityPersistenceError) as exc_info:
        _resolver().register_slug("42", "   ")
    assert exc_info.value.article_id == "42"
    assert str(exc_info.value).endswith(
        "(DB outage or missing row). empty slug refused"
    )


def test_register_slug_without_db_method_raises_persistence_error() -> None:
    with pytest.raises(IdentityPersistenceError) as exc_info:
        _resolver(db=SimpleNamespace()).register_slug("42", "2024-01-01-x")
    assert exc_info.value.article_id == "42"
    assert str(exc_info.value).endswith(
        "(DB outage or missing row). DB has no set_canonical_slug"
    )


def test_register_slug_outage_carries_article_id_and_cause() -> None:
    class _OutageDB:
        def set_canonical_slug(self, article_id: str, slug: str) -> bool:
            raise RuntimeError("db down")

    with pytest.raises(IdentityPersistenceError) as exc_info:
        _resolver(db=_OutageDB()).register_slug("42", "2024-01-01-x")
    assert exc_info.value.article_id == "42"
    assert str(exc_info.value).endswith("(DB outage or missing row). db down")


def test_register_slug_collision_carries_article_id_and_slug() -> None:
    db = _RecordingDB(set_result=False)
    with pytest.raises(SlugCollisionError) as exc_info:
        _resolver(db=db).register_slug("42", "2024-01-01-x")
    assert exc_info.value.article_id == "42"
    assert exc_info.value.slug == "2024-01-01-x"


def test_resolve_backfill_failure_carries_article_id(tmp_path: Path) -> None:
    existing = tmp_path / "2024-01-01-recovered.md"
    existing.write_text("---\n---\nbody", encoding="utf-8")
    db = _RecordingDB(set_result=False)
    resolver = _resolver(db=db, manifest=_Manifest(existing=existing))
    with pytest.raises(IdentityPersistenceError) as exc_info:
        resolver.resolve(article_id="77", article={}, posts_dir=tmp_path)
    assert exc_info.value.article_id == "77"
    assert str(exc_info.value).endswith(
        "(DB outage or missing row). FS-recovered slug "
        "'2024-01-01-recovered' could not be locked"
    )


# ---------------------------------------------------------------------------
# Resolver lookups use the caller's id and the caller's posts dir
# ---------------------------------------------------------------------------


def test_resolve_queries_db_and_manifest_with_article_id(tmp_path: Path) -> None:
    db = _RecordingDB(slug=None)
    manifest = _Manifest()
    identity = _resolver(db=db, manifest=manifest).resolve(
        article_id="abc", article={"published_date": "2024-01-25"}, posts_dir=tmp_path
    )
    assert db.get_calls == ["abc"]
    assert manifest.calls == [(tmp_path, "abc")]
    assert identity.final_slug == "2024-01-25-article-abc"
    assert identity.output_filename == "2024-01-25-article-abc.md"


def test_resolve_with_db_that_lacks_get_method_still_creates(tmp_path: Path) -> None:
    identity = _resolver(db=SimpleNamespace()).resolve(
        article_id="abc", article={"published_date": "2024-01-25"}, posts_dir=tmp_path
    )
    assert identity.final_slug == "2024-01-25-article-abc"


# ---------------------------------------------------------------------------
# Creation mode: title slug, fallback, collision bumps
# ---------------------------------------------------------------------------


def test_creation_mode_slug_uses_title(tmp_path: Path) -> None:
    identity = _resolver().resolve(
        article_id="abc",
        article={"published_date": "2024-01-25", "title": "Hola Mundo"},
        posts_dir=tmp_path,
    )
    assert identity.final_slug == "2024-01-25-hola-mundo"
    assert identity.output_filename == "2024-01-25-hola-mundo.md"
    assert identity.is_new is True


def test_creation_mode_untitleable_uses_article_id_fallback(tmp_path: Path) -> None:
    identity = _resolver().resolve(
        article_id="42",
        article={"published_date": "2024-01-25", "title": "???"},
        posts_dir=tmp_path,
    )
    assert identity.final_slug == "2024-01-25-article-42"


def test_extract_slug_prefers_slug_field_over_title() -> None:
    assert (
        PublicationIdentityResolver.extract_slug(
            "slug: canonical-slug\ntitle: Other Title", "9"
        )
        == "canonical-slug"
    )


def test_resolve_collision_bumps_twice(tmp_path: Path) -> None:
    (tmp_path / "2024-01-25-hola-mundo.md").write_text("", encoding="utf-8")
    (tmp_path / "2024-01-25-hola-mundo-1.md").write_text("", encoding="utf-8")
    identity = _resolver().resolve(
        article_id="abc",
        article={"published_date": "2024-01-25", "title": "Hola Mundo"},
        posts_dir=tmp_path,
    )
    assert identity.final_slug == "2024-01-25-hola-mundo-2"
    assert identity.output_filename == "2024-01-25-hola-mundo-2.md"


def test_finalize_slug_passes_article_id_to_extract_fn(tmp_path: Path) -> None:
    seen: list[tuple[str, str]] = []

    def _extract(content: str, article_id: str) -> str:
        seen.append((content, article_id))
        return "custom-slug"

    identity = PublicationIdentity(
        final_slug="2024-01-25-provisional",
        canonical_date="2024-01-25",
        output_filename="2024-01-25-provisional.md",
        is_new=True,
    )
    out = _resolver().finalize_slug(
        identity, "refined content", "42", tmp_path, extract_slug_fn=_extract
    )
    assert seen == [("refined content", "42")]
    assert out.final_slug == "2024-01-25-custom-slug"
    assert out.output_filename == "2024-01-25-custom-slug.md"


def test_finalize_slug_collision_bumps_twice(tmp_path: Path) -> None:
    identity = PublicationIdentity(
        final_slug="2024-01-25-hola-mundo",
        canonical_date="2024-01-25",
        output_filename="2024-01-25-hola-mundo.md",
        is_new=True,
    )
    (tmp_path / "2024-01-25-hola-mundo.md").write_text("", encoding="utf-8")
    (tmp_path / "2024-01-25-hola-mundo-1.md").write_text("", encoding="utf-8")
    out = _resolver().finalize_slug(identity, "title: Hola Mundo", "abc", tmp_path)
    assert out.final_slug == "2024-01-25-hola-mundo-2"


# ---------------------------------------------------------------------------
# Date-shape parsing through the public resolver
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (datetime(2024, 1, 25, 10, 0, tzinfo=timezone.utc), "2024-01-25"),
        (datetime(2024, 1, 25, 10, 0), "2024-01-25"),
        (date(2024, 1, 25), "2024-01-25"),
        ("2024-01-25T10:00:00+00:00", "2024-01-25"),
        ("2024-01-25 10:00:00", "2024-01-25"),
        ("2024-01-25Z", "2024-01-25"),
        ("2024-01-25z", "2024-01-25"),
        (20240125, "2024-01-25"),
        ("2024-01-25", "2024-01-25"),
    ],
)
def test_published_date_shapes(tmp_path: Path, raw: object, expected: str) -> None:
    identity = _resolver().resolve(
        article_id="1", article={"published_date": raw}, posts_dir=tmp_path
    )
    assert identity.canonical_date == expected


def test_unparseable_published_date_error_carries_id_and_field(
    tmp_path: Path,
) -> None:
    with pytest.raises(UndatedArticleError) as exc_info:
        _resolver().resolve(
            article_id="88",
            article={"id": "88", "published_date": "garbage"},
            posts_dir=tmp_path,
        )
    assert exc_info.value.article_id == "88"
    assert exc_info.value.field == "published_date"
    assert str(exc_info.value).endswith("date. unparseable value 'garbage'")


def test_both_dates_missing_error_uses_unknown_default_id(tmp_path: Path) -> None:
    with pytest.raises(UndatedArticleError) as exc_info:
        _resolver().resolve(article_id="99", article={}, posts_dir=tmp_path)
    assert exc_info.value.article_id == "unknown"
    assert exc_info.value.field == "published_date/collected_date"
    assert str(exc_info.value).endswith(
        "no usable published_date/collected_date for canonical publication "
        "identity — refusing to invent a non-deterministic date."
    )


def test_manual_ingest_inference_passthrough_and_clock() -> None:
    present = datetime(2024, 1, 25, tzinfo=timezone.utc)
    assert infer_manual_published_date(present) == (present, False)
    inferred, flag = infer_manual_published_date(None)
    assert flag is True
    assert inferred.tzinfo is timezone.utc


# ---------------------------------------------------------------------------
# Atomic exclusive create (O_EXCL claim)
# ---------------------------------------------------------------------------


def test_exclusive_create_file_creates_nested_dirs_and_writes_content(
    tmp_path: Path,
) -> None:
    posts_dir = tmp_path / "a" / "b" / "posts"
    target = PublicationIdentityResolver.exclusive_create_file(
        posts_dir, "post.md", "hello"
    )
    assert target == posts_dir / "post.md"
    assert target.read_text(encoding="utf-8") == "hello"


def test_exclusive_create_file_default_content_is_empty(tmp_path: Path) -> None:
    target = PublicationIdentityResolver.exclusive_create_file(tmp_path, "empty.md")
    assert target.read_text(encoding="utf-8") == ""


def test_exclusive_create_file_refuses_second_claim(tmp_path: Path) -> None:
    PublicationIdentityResolver.exclusive_create_file(tmp_path, "dup.md")
    with pytest.raises(SlugCollisionError) as exc_info:
        PublicationIdentityResolver.exclusive_create_file(tmp_path, "dup.md")
    assert exc_info.value.article_id == ""
    assert exc_info.value.slug == "dup.md"
    assert exc_info.value.error_code == "E_IDENTITY_SLUG_COLLISION"


def test_exclusive_create_file_refuses_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(IdentityPersistenceError) as exc_info:
        PublicationIdentityResolver.exclusive_create_file(tmp_path, "../escape.md")
    assert exc_info.value.article_id == ""
    assert str(exc_info.value).endswith("path traversal refused for '../escape.md'")


def test_exclusive_create_file_wraps_os_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise OSError("disk full")

    monkeypatch.setattr(identity_mod.os, "open", _boom)
    with pytest.raises(IdentityPersistenceError) as exc_info:
        PublicationIdentityResolver.exclusive_create_file(tmp_path, "x.md")
    assert exc_info.value.article_id == ""
    assert str(exc_info.value).endswith("(DB outage or missing row). disk full")
