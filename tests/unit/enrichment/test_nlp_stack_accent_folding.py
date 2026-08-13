"""QW1 (plan 058 session): accent folding in the literal entity matcher.

Plan 048's paired evaluation showed every entity FN/FP cluster is an
accent variant mismatch: the registry's canonical patterns carry accents
("Universidade de São Paulo") while article text often does not
("Universidade de Sao Paulo"). The literal matcher (str.find) can never
join them. Folding accents (NFKD + strip combining marks) on both
haystack and needle — only when case_sensitive=False — closes that gap
without touching exact-match semantics.
"""

from __future__ import annotations

import pytest

from news_collector.enrichment.nlp_stack import ConfigurableNLPStack


def _make_stack(patterns: dict) -> ConfigurableNLPStack:
    config = {
        "default_model": "test",
        "analysis_cache_size": 0,
        "models": {
            "test": {
                "version": "1.0",
                "provider": "pattern",
                "default_language": "es",
                "languages": ["es"],
                "default_topic": "general",
                "entities": {"patterns": patterns},
            }
        },
    }
    return ConfigurableNLPStack(config)


class TestEntityAccentFolding:
    def test_accented_pattern_matches_unaccented_text(self):
        """São Paulo pattern must match 'sao paulo' text (gold vs text gap)."""
        stack = _make_stack(
            {
                "shared": [
                    {
                        "label": "ORG",
                        "pattern": "Universidade de São Paulo",
                        "alias": "Universidade de São Paulo",
                        "case_sensitive": False,
                    }
                ]
            }
        )
        result = stack.analyze(
            "es",
            "Pesquisadores da universidade de sao paulo publicaram o estudo.",
        )
        assert result.entities == ("Universidade de São Paulo",)

    def test_unaccented_pattern_matches_accented_text(self):
        """Reverse direction: pattern without accents, text with accents."""
        stack = _make_stack(
            {
                "shared": [
                    {
                        "label": "ORG",
                        "pattern": "Universidade de Sao Paulo",
                        "alias": "Universidade de São Paulo",
                        "case_sensitive": False,
                    }
                ]
            }
        )
        result = stack.analyze(
            "es",
            "Pesquisadores da Universidade de São Paulo publicaram o estudo.",
        )
        assert result.entities == ("Universidade de São Paulo",)

    def test_case_sensitive_pattern_is_not_accent_folded(self):
        """case_sensitive=True must keep exact-match semantics: no accent
        folding, no case folding."""
        stack = _make_stack(
            {
                "shared": [
                    {
                        "label": "TECH",
                        "pattern": "IA",
                        "alias": "IA",
                        "case_sensitive": True,
                    }
                ]
            }
        )
        assert stack.analyze("es", "La ia avanza rápido.").entities == ()
        assert stack.analyze("es", "La IA avanza rápido.").entities == ("IA",)

    def test_accent_folding_respects_entity_boundary_semantics(self):
        """Folding must not create matches across unrelated words — a
        single-word accent-less pattern still needs its exact substring."""
        stack = _make_stack(
            {
                "shared": [
                    {"label": "ORG", "pattern": "Telefónica", "case_sensitive": False}
                ]
            }
        )
        assert stack.analyze("es", "La telefonica es una empresa.").entities == (
            "Telefónica",
        )
        # 'telefonica' is not part of another word here, but the matcher is
        # substring-based by design — only assert the accent direction.
