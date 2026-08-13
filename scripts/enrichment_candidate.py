#!/usr/bin/env python3
"""Plan 048 Step 4 — curated candidate registry (isolated from production).

Builds a candidate enrichment config that addresses the measured errors
of pattern_v1 on the 44-record reviewed corpus:

  FN topics  : science (9) — "estudio/estudio científico/étude/recherche"
               not matched; economy (3) — "FMI/IMF" not in keywords
  FP topics  : general (5) — overuse of fallback; science (3)
  FP entities: ESA (4) — substring collision ('esa' inside other words)
  FN entities: FMI (4), Universidade de Sao Paulo (3), Ariane 6 (2),
               Agence spatiale europeenne (2)

The candidate is a pure dict, evaluated offline against the same corpus
by the plan's evaluator. It is NOT wired into production config.toml —
adoption is the ADR's decision (Step 6).
"""

from __future__ import annotations

CANDIDATE_MODEL = "curated_candidate"

CANDIDATE_CONFIG = {
    "models": {
        CANDIDATE_MODEL: {
            "version": "2026.08-curated-candidate",
            "provider": "pattern",
            "default_topic": "general",
            "default_language": "en",
            "languages": ["en", "es", "pt", "fr"],
            "topics": {
                "space": {
                    "keywords": {
                        "shared": [
                            "space",
                            "espacio",
                            "espaço",
                            "lunar",
                            "luna",
                            "moon",
                            "orbit",
                            "orbital",
                            # NOTE: 'satellite'/'satélite' deliberately EXCLUDED
                            # — satellite data is ubiquitous in Earth-observation
                            # and climate monitoring (plan 048 Step 5 found it
                            # caused a space FP in slice pt-climate-pos-019).
                            "rocket",
                            "foguete",
                            "cohete",
                            "fusée",
                            "lanceur",
                            "mission spatiale",
                            "misión espacial",
                            "nasa",
                            "esa",
                            "agence spatiale",
                            "agência espacial",
                        ]
                    }
                },
                "science": {
                    "keywords": {
                        "shared": [
                            "science",
                            "ciencia",
                            "ciência",
                            "scientifique",
                            "recherche",
                            "research",
                            "investigación",
                            "pesquisa",
                            "laboratorio",
                            "laboratory",
                            "laboratoire",
                            "study",
                            "estudio",
                            "estudo",
                            "étude",
                            "estudi",
                            "study",
                            "peer-reviewed",
                            "revisado por pares",
                            "revisada por pares",
                            "évalué",
                            "científic",
                            "científ",
                            "scientific",
                            "scientist",
                            "investigadores",
                            "pesquisadores",
                            "researchers",
                        ]
                    }
                },
                "health": {
                    "keywords": {
                        "shared": [
                            "health",
                            "salud",
                            "saúde",
                            "santé",
                            "flu",
                            "gripe",
                            "grippe",
                            "vacun",
                            "vaccin",
                            "vaccin",
                            "hospital",
                            "ministère de la santé",
                            "ministerio de salud",
                            "ministério da saúde",
                        ]
                    }
                },
                "technology": {
                    "keywords": {
                        "shared": [
                            "technology",
                            "tecnología",
                            "tecnologia",
                            "technologie",
                            "tech",
                            "ai",
                            "inteligencia artificial",
                            "inteligência artificial",
                            "intelligence artificielle",
                            "artificial intelligence",
                            "platform",
                            "plataforma",
                            "startup",
                            "tool",
                            "herramienta",
                            "ferramenta",
                            "outil",
                        ]
                    }
                },
                "climate": {
                    "keywords": {
                        "shared": [
                            "climate",
                            "clima",
                            "climat",
                            "climático",
                            "climatic",
                            "climatique",
                            "emissions",
                            "emisiones",
                            "emissões",
                            "émissions",
                            "glacier",
                            "glaciares",
                            "amazonia",
                            "amazônia",
                            "amazon",
                            "resilience",
                            "resiliencia",
                        ]
                    }
                },
                "economy": {
                    "keywords": {
                        "shared": [
                            "economy",
                            "economía",
                            "economia",
                            "économie",
                            "económic",
                            "econôm",
                            "économ",
                            "market",
                            "mercado",
                            "marché",
                            "growth",
                            "crecimiento",
                            "crescimento",
                            "croissance",
                            "inflation",
                            "inflación",
                            "inflação",
                            "recession",
                            "recesión",
                            "recessão",
                            "fmi",
                            "imf",
                            "reprise",
                            "recuperación",
                            "recuperação",
                        ]
                    }
                },
            },
            "entities": {
                # NOTE: direct injection into ConfigurableNLPStack (no
                # settings._normalize_enrichment), so the structure is the
                # NORMALIZED one: entities.patterns.{shared,<lang>}.
                # The matcher uses literal substring search (str.find),
                # not regex — full-word multi-token patterns are the
                # reliable disambiguation; short codes that collide as
                # substrings ('ESA' inside 'esa') are language-scoped.
                "patterns": {
                    "shared": [
                        {
                            "label": "ORG",
                            "pattern": "NASA",
                            "alias": "NASA",
                            "case_sensitive": False,
                        },
                        {
                            "label": "ORG",
                            "pattern": "IMF",
                            "alias": "IMF",
                            "case_sensitive": False,
                        },
                        {
                            "label": "ORG",
                            "pattern": "FMI",
                            "alias": "FMI",
                            "case_sensitive": False,
                        },
                        {
                            "label": "PRODUCT",
                            "pattern": "Orion",
                            "alias": "Orion",
                            "case_sensitive": False,
                        },
                        {
                            "label": "PRODUCT",
                            "pattern": "Ariane 6",
                            "alias": "Ariane 6",
                            "case_sensitive": False,
                        },
                        {
                            "label": "ORG",
                            "pattern": "Telefónica",
                            "alias": "Telefónica",
                            "case_sensitive": False,
                        },
                        {
                            "label": "ORG",
                            "pattern": "Universidade de São Paulo",
                            "alias": "Universidade de São Paulo",
                            "case_sensitive": False,
                        },
                        {
                            "label": "ORG",
                            "pattern": "Universidade de Sao Paulo",
                            "alias": "Universidade de São Paulo",
                            "case_sensitive": False,
                        },
                        {
                            "label": "ORG",
                            "pattern": "Universidad Nacional Autónoma de México",
                            "alias": "Universidad Nacional Autónoma de México",
                            "case_sensitive": False,
                        },
                        {
                            "label": "ORG",
                            "pattern": "Universidad Nacional Autonoma de Mexico",
                            "alias": "Universidad Nacional Autónoma de México",
                            "case_sensitive": False,
                        },
                        {
                            "label": "ORG",
                            "pattern": "Agence spatiale européenne",
                            "alias": "Agence spatiale européenne",
                            "case_sensitive": False,
                        },
                        {
                            "label": "ORG",
                            "pattern": "Agence spatiale europeenne",
                            "alias": "Agence spatiale européenne",
                            "case_sensitive": False,
                        },
                        {
                            "label": "ORG",
                            "pattern": "Ministerio de Salud de Chile",
                            "alias": "Ministerio de Salud de Chile",
                            "case_sensitive": False,
                        },
                        {
                            "label": "ORG",
                            "pattern": "Ministério da Saúde",
                            "alias": "Ministério da Saúde",
                            "case_sensitive": False,
                        },
                        {
                            "label": "ORG",
                            "pattern": "Ministère de la Santé",
                            "alias": "Ministère de la Santé",
                            "case_sensitive": False,
                        },
                    ],
                    # ESA is substring-unsafe in es/pt ('esa' is a common
                    # word); scope the short code to en/fr only.
                    "en": [
                        {
                            "label": "ORG",
                            "pattern": "ESA",
                            "alias": "ESA",
                            "case_sensitive": False,
                        },
                    ],
                    "fr": [
                        {
                            "label": "ORG",
                            "pattern": "ESA",
                            "alias": "ESA",
                            "case_sensitive": False,
                        },
                    ],
                }
            },
        }
    },
    "default_model": CANDIDATE_MODEL,
}
