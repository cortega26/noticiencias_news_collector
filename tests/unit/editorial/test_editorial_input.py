"""
tests/unit/editorial/test_editorial_input.py

Verifies the normalized editorial input contract and the typed stage cache
identities (plan 060 Phase 7c-1).
"""

from __future__ import annotations

import hashlib

from news_collector.components.editorial.editorial_input import EditorialInput
from news_collector.components.editorial.editorial_stages import EditorialStage


class TestFromRawDict:
    def test_full_payload_fields_are_extracted(self):
        raw = {
            "id": 7,
            "title": "Título",
            "summary": "Resumen",
            "content": "Contenido",
            "content_mode": "summary_only",
            "image_url": "https://example.com/img.png",
            "image_alt": "Alt",
            "source_id": "src",
            "source_name": "Fuente",
            "url": "https://example.com/source",
            "category": "science",
            "metadata": {"category": "meta-category"},
        }

        result = EditorialInput.from_raw(raw)

        assert result.article_id == "7"
        assert result.title == "Título"
        assert result.summary == "Resumen"
        assert result.content == "Contenido"
        assert result.content_mode == "summary_only"
        assert result.image_url == "https://example.com/img.png"
        assert result.image_alt == "Alt"
        assert result.source_id == "src"
        assert result.source_name == "Fuente"
        assert result.source_url == "https://example.com/source"
        assert result.raw_category == "science"
        assert result.metadata_category == "meta-category"

    def test_content_falls_back_to_summary_when_empty(self):
        result = EditorialInput.from_raw(
            {"id": "1", "summary": "Solo resumen", "content": ""}
        )
        assert result.content == "Solo resumen"

    def test_content_mode_defaults_to_full_text(self):
        result = EditorialInput.from_raw({"id": "1", "content": "x"})
        assert result.content_mode == "full_text"

    def test_missing_fields_default(self):
        result = EditorialInput.from_raw({"id": "1", "content": "x"})
        assert result.title == ""
        assert result.summary == ""
        assert result.image_url is None
        assert result.image_alt is None
        assert result.source_id is None
        assert result.source_name is None
        assert result.source_url is None
        assert result.raw_category is None
        assert result.metadata_category is None

    def test_source_url_prefers_url(self):
        result = EditorialInput.from_raw(
            {
                "id": "1",
                "content": "x",
                "url": "https://direct",
                "metadata": {"original_url": "https://original"},
            }
        )
        assert result.source_url == "https://direct"

    def test_source_url_falls_back_to_metadata_original_url(self):
        result = EditorialInput.from_raw(
            {
                "id": "1",
                "content": "x",
                "metadata": {"original_url": "https://original"},
            }
        )
        assert result.source_url == "https://original"

    def test_source_url_falls_back_to_entry_id(self):
        result = EditorialInput.from_raw(
            {
                "id": "1",
                "content": "x",
                "metadata": {"source_metadata": {"entry_id": "entry-9"}},
            }
        )
        assert result.source_url == "entry-9"

    def test_metadata_none_is_safe(self):
        result = EditorialInput.from_raw({"id": "1", "content": "x", "metadata": None})
        assert result.source_url is None
        assert result.metadata_category is None

    def test_explicit_article_id_wins_over_dict_id(self):
        result = EditorialInput.from_raw({"id": 7, "content": "x"}, "99")
        assert result.article_id == "99"

    def test_dict_id_used_when_explicit_missing(self):
        result = EditorialInput.from_raw({"id": 7, "content": "x"})
        assert result.article_id == "7"

    def test_unknown_id_when_neither_explicit_nor_dict(self):
        result = EditorialInput.from_raw({"content": "x"})
        assert result.article_id == "unknown"

    def test_explicit_unknown_falls_through_to_dict_id(self):
        result = EditorialInput.from_raw({"id": 7, "content": "x"}, "unknown")
        assert result.article_id == "7"


class TestFromRawString:
    def test_string_input_hashes_the_content(self):
        content = "Raw article text"
        result = EditorialInput.from_raw(content)
        assert result.article_id == hashlib.sha256(content.encode()).hexdigest()[:8]
        assert result.content == content
        assert result.content_mode == "full_text"
        assert result.title == ""
        assert result.summary == ""
        assert result.image_url is None
        assert result.source_url is None
        assert result.raw_category is None
        assert result.metadata_category is None

    def test_explicit_id_overrides_content_hash(self):
        result = EditorialInput.from_raw("Raw article text", "1234")
        assert result.article_id == "1234"


class TestEditorialStage:
    def test_values_are_the_legacy_cache_keys(self):
        assert EditorialStage.TRANSLATION.value == "stage1_translation"
        assert EditorialStage.EDITORIAL.value == "stage2_editorial"
        assert EditorialStage.TECHNICAL_CRITIC_OK.value == "stage2_5_critic_ok"
        assert (
            EditorialStage.EDITORIAL_CRITIC_OK.value == "stage2_6_editorial_critic_ok"
        )
        assert EditorialStage.ENRICHMENT.value == "stage4_enrichment"

    def test_formats_as_the_legacy_cache_filename_stem(self):
        assert (
            f"abc_{EditorialStage.TECHNICAL_CRITIC_OK}.txt"
            == "abc_stage2_5_critic_ok.txt"
        )
        assert str(EditorialStage.ENRICHMENT) == "stage4_enrichment"
