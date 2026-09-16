"""Plan 101: the collector language set is an explicit snapshot.

- Unset snapshot -> {"en", "es"} bootstrap default.
- set_supported_languages() -> the validator honors it.
- refresh_runtime_config() pushes the runtime set (bootstrap wiring).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from news_collector.config import settings as config_settings
from news_collector.contracts import collector as collector_contracts
from news_collector.contracts.collector import (
    CollectorArticleModel,
    _supported_languages,
    set_supported_languages,
)


@pytest.fixture(autouse=True)
def _restore_language_snapshot():
    saved = collector_contracts._SUPPORTED_LANGUAGES
    try:
        yield
    finally:
        collector_contracts._SUPPORTED_LANGUAGES = saved


def _payload(language="en"):
    return {
        "url": "http://example.com/lang-snapshot",
        "title": "A very long title that meets the requirements",
        "summary": "Short summary",
        "content": "A" * 501,
        "source_id": "test_src",
        "source_name": "Test Source",
        "category": "science",
        "published_date": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "language": language,
    }


def test_unset_snapshot_falls_back_to_bootstrap_default():
    collector_contracts._SUPPORTED_LANGUAGES = None
    assert _supported_languages() == {"en", "es"}
    assert CollectorArticleModel(**_payload("es")).language == "es"
    with pytest.raises(ValidationError) as exc:
        CollectorArticleModel(**_payload("fr"))
    assert "language" in str(exc.value)


def test_setter_snapshot_is_honored_by_validator():
    set_supported_languages(["en", "fr"])
    assert _supported_languages() == {"en", "fr"}
    assert CollectorArticleModel(**_payload("fr")).language == "fr"
    with pytest.raises(ValidationError) as exc:
        CollectorArticleModel(**_payload("es"))
    assert "language" in str(exc.value)


def test_refresh_runtime_config_pushes_snapshot():
    snapshot = config_settings.refresh_runtime_config()
    expected = set(
        snapshot.text_processing_config.get("supported_languages", ["en", "es"])
    )
    assert _supported_languages() == expected
