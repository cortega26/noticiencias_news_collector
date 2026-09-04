import json
from datetime import datetime, timezone

import pytest

from apps.refinery.main import _load_export_articles
from news_collector.config.sources import ALL_SOURCES
from news_collector.contracts.adapters import adapt_export_article_to_collector_payload
from news_collector.contracts.collector import CollectorArticleModel


class _DummyDB:
    def is_article_published(self, _article_id: int) -> bool:
        return False


def test_load_export_articles_backfills_source_id_from_source_name(tmp_path):
    source_id, source_cfg = next(
        (sid, cfg)
        for sid, cfg in ALL_SOURCES.items()
        if str(cfg.get("name", "")).strip()
    )
    source_name = str(source_cfg["name"]).strip()

    export_path = tmp_path / "latest_articles.json"
    export_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "contract": "news_collector.export.v1",
                "articles": [
                    {
                        "id": 160,
                        "title": "Legacy export item with missing source_id",
                        "url": "https://example.com/article-160",
                        "summary": "Valid summary for refinery contract",
                        "content": "Valid content body for refinery contract checks.",
                        "source_name": source_name,
                        "category": "science",
                        "published_date": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    articles = _load_export_articles(export_path, _DummyDB(), process_id="160")
    assert len(articles) == 1
    assert articles[0]["source_id"] == source_id


def test_streamlit_like_payload_validates_contract_after_loading(tmp_path):
    source_id, source_cfg = next(
        (sid, cfg)
        for sid, cfg in ALL_SOURCES.items()
        if str(cfg.get("name", "")).strip()
    )
    source_name = str(source_cfg["name"]).strip()

    export_path = tmp_path / "latest_articles.json"
    export_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "contract": "news_collector.export.v1",
                "articles": [
                    {
                        "id": 160,
                        "title": "Another legacy payload without source_id",
                        "url": "https://example.com/article-160-b",
                        "summary": "Valid summary for contract validation",
                        "content": "Valid content body for contract validation.",
                        "source_name": source_name,
                        "category": "science",
                        "published_date": "2026-02-20T14:00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    article = _load_export_articles(export_path, _DummyDB(), process_id="160")[0]
    model = CollectorArticleModel.model_validate(article)

    assert model.source_id == source_id
    assert model.source_name == source_name
    assert model.published_date.tzinfo == timezone.utc


def test_load_export_articles_warns_on_legacy_schema(tmp_path, monkeypatch):
    source_id, source_cfg = next(
        (sid, cfg)
        for sid, cfg in ALL_SOURCES.items()
        if str(cfg.get("name", "")).strip()
    )
    source_name = str(source_cfg["name"]).strip()

    export_path = tmp_path / "latest_articles.json"
    export_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "contract": "news_collector.export.v1",
                "articles": [
                    {
                        "id": 160,
                        "title": "Legacy payload with warning path",
                        "url": "https://example.com/article-160-c",
                        "summary": "Valid summary for warning path",
                        "content": "Valid content body for warning path.",
                        "source_name": source_name,
                        "category": "science",
                        "published_date": "2026-02-20T14:00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    warnings = []

    def _capture_warning(message, *args, **kwargs):
        warnings.append(str(message))

    monkeypatch.setattr("apps.refinery.main.logger.warning", _capture_warning)
    articles = _load_export_articles(export_path, _DummyDB(), process_id="160")

    assert len(articles) == 1
    assert articles[0]["source_id"] == source_id
    assert any("Legacy export schema detected" in msg for msg in warnings)


def skip_test_schema_v2_missing_source_id_is_rejected_without_legacy_fallback(tmp_path):
    source_id, source_cfg = next(
        (sid, cfg)
        for sid, cfg in ALL_SOURCES.items()
        if str(cfg.get("name", "")).strip()
    )
    source_name = str(source_cfg["name"]).strip()

    export_path = tmp_path / "latest_articles.json"
    export_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "contract": "news_collector.export.v2",
                "articles": [
                    {
                        "id": 160,
                        "title": "V2 payload should not fallback from source_name",
                        "url": "https://example.com/article-160-d",
                        "summary": "Valid summary for strict v2 path",
                        "content": "Valid content body for strict v2 path.",
                        "source_name": source_name,
                        "category": "science",
                        "published_date": "2026-02-20T14:00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert _load_export_articles(export_path, _DummyDB(), process_id="160") == []


def test_adapter_rejects_payload_without_deterministic_source_identity():
    with pytest.raises(
        ValueError,
        match="Missing source_id in export payload and deterministic fallback failed",
    ):
        adapt_export_article_to_collector_payload(
            {
                "id": 160,
                "title": "Legacy article",
                "source_name": "Unknown Source",
            },
            source_name_to_id={"known source": "known_id"},
        )


def test_source_registry_names_are_casefold_unique():
    seen: dict[str, str] = {}
    duplicates: list[tuple[str, str, str]] = []
    for source_id, source_cfg in ALL_SOURCES.items():
        source_name = str(source_cfg.get("name", "")).strip()
        if not source_name:
            continue
        key = source_name.casefold()
        if key in seen and seen[key] != source_id:
            duplicates.append((key, seen[key], source_id))
        else:
            seen[key] = source_id
    assert duplicates == []


def test_adapter_source_name_fallback_is_case_insensitive():
    normalized = adapt_export_article_to_collector_payload(
        {
            "id": 160,
            "title": "Legacy article with uppercase source name",
            "source_name": "LIL'LOG",
        },
        source_name_to_id={"lil'log": "lilian_weng"},
    )
    assert normalized["source_id"] == "lilian_weng"


class _IdentityDB:
    """db_manager stub for the plan-071 identity guard tests."""

    def __init__(self, row=None, raise_on_lookup=False):
        self._row = row
        self._raise = raise_on_lookup

    def is_article_published(self, _article_id):
        return False

    def get_article_by_id(self, _article_id):
        if self._raise:
            raise RuntimeError("db down")
        return self._row


def _identity_export(tmp_path, article):
    export_path = tmp_path / "latest_articles.json"
    export_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "contract": "news_collector.export.v1",
                "articles": [article],
            }
        ),
        encoding="utf-8",
    )
    return export_path


def _identity_article(**overrides):
    from news_collector.config.sources import ALL_SOURCES as _SOURCES

    _sid, _cfg = next(
        (sid, cfg) for sid, cfg in _SOURCES.items() if str(cfg.get("name", "")).strip()
    )
    base = {
        "id": 160,
        "title": "Tornado science article",
        "url": "https://example.com/tornado-160",
        "summary": "Valid summary for refinery contract",
        "content": "Valid content body for refinery contract checks.",
        "source_name": str(_cfg["name"]).strip(),
        "category": "science",
        "published_date": datetime.now(timezone.utc).isoformat(),
    }
    base.update(overrides)
    return base


def _identity_row(
    title="Tornado science article", url="https://example.com/tornado-160"
):
    from types import SimpleNamespace

    return SimpleNamespace(title=title, url=url)


def test_export_identity_match_keeps_article(tmp_path):
    export_path = _identity_export(tmp_path, _identity_article())
    articles = _load_export_articles(
        export_path, _IdentityDB(row=_identity_row()), process_id="160"
    )
    assert len(articles) == 1


def test_export_identity_title_mismatch_drops_article(tmp_path, caplog):
    export_path = _identity_export(tmp_path, _identity_article())
    articles = _load_export_articles(
        export_path,
        _IdentityDB(row=_identity_row(title="A completely different piece")),
        process_id="160",
    )
    assert articles == []


def test_export_identity_url_mismatch_drops_article(tmp_path):
    export_path = _identity_export(tmp_path, _identity_article())
    articles = _load_export_articles(
        export_path,
        _IdentityDB(row=_identity_row(url="https://example.com/other")),
        process_id="160",
    )
    assert articles == []


def test_export_identity_unknown_id_drops_article(tmp_path):
    export_path = _identity_export(tmp_path, _identity_article())
    articles = _load_export_articles(
        export_path, _IdentityDB(row=None), process_id="160"
    )
    assert articles == []


def test_export_identity_db_failure_fails_open(tmp_path):
    export_path = _identity_export(tmp_path, _identity_article())
    articles = _load_export_articles(
        export_path,
        _IdentityDB(row=_identity_row(), raise_on_lookup=True),
        process_id="160",
    )
    assert len(articles) == 1


def test_export_identity_non_numeric_process_id_untouched(tmp_path):
    article = _identity_article()
    del article["id"]
    export_path = _identity_export(tmp_path, article)
    articles = _load_export_articles(
        export_path,
        _IdentityDB(row=_identity_row(title="Tornado science article")),
        process_id="Tornado science article",
    )
    assert len(articles) == 1
