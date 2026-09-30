"""Unit tests for deterministic publication repair strategies (self-healing).

`repair_post_content` is the pure half of the bounded self-correction loop in
`TargetRepoPublicationWorkflow`: it must only return a repaired post when the
targeted contract invariant is restored, and must never raise.
"""

from __future__ import annotations

from types import SimpleNamespace

import yaml

from news_collector.taxonomy.normalizer import TagNormalizer
from news_collector.validation.publication_repairs import (
    repair_post_content,
    repairable_failure_classes,
)

POST = """---
title: La gravedad como proyector holográfico
tags:
  - ads/cft
  - principio holográfico
  - agujero negro
image_alt: La gravedad como proyector holográfico
---

Cuerpo con / barras y --- guiones que no son delimitadores.
"""


def _body(content: str) -> str:
    return content.split("\n---", 1)[1]


def _frontmatter(content: str) -> dict:
    return yaml.safe_load(content.split("---\n", 2)[1])


def test_repairs_tag_charset_and_preserves_body():
    repair = repair_post_content(POST, "taxonomy_contract_violation")

    assert repair is not None
    assert "ads cft" in repair.content
    assert "ads/cft" not in repair.content
    assert repair.fields == ("tags",)
    assert repair.descriptions
    # Body is byte-identical; only the frontmatter changed.
    assert _body(repair.content) == _body(POST)


def test_repaired_output_satisfies_the_tag_contract():
    repair = repair_post_content(POST, "taxonomy_contract_violation")

    assert repair is not None
    tags = _frontmatter(repair.content)["tags"]
    assert TagNormalizer().validate_tags(tags).is_valid


def test_valid_tags_return_none():
    valid = POST.replace("ads/cft", "ads cft")
    assert repair_post_content(valid, "taxonomy_contract_violation") is None


def test_unknown_failure_class_returns_none():
    assert repair_post_content(POST, "frontend_build_failure") is None
    assert repair_post_content(POST, "not_a_class") is None


def test_malformed_or_missing_frontmatter_returns_none():
    assert (
        repair_post_content("No frontmatter here", "taxonomy_contract_violation")
        is None
    )
    assert (
        repair_post_content("---\ntags: [ads/cft]\n", "taxonomy_contract_violation")
        is None
    )
    assert (
        repair_post_content(
            "---\ntags:\n  - {broken: [\n---\nBody", "taxonomy_contract_violation"
        )
        is None
    )


def test_non_string_or_missing_tags_return_none():
    assert (
        repair_post_content(
            "---\ntags:\n  - 42\n  - true\n---\nBody", "taxonomy_contract_violation"
        )
        is None
    )
    assert (
        repair_post_content("---\ntitle: T\n---\nBody", "taxonomy_contract_violation")
        is None
    )


def test_repairable_failure_classes_exposed():
    assert repairable_failure_classes() == ("taxonomy_contract_violation",)


def test_empty_content_returns_none():
    assert repair_post_content("", "taxonomy_contract_violation") is None


def test_non_mapping_frontmatter_returns_none():
    assert (
        repair_post_content("---\n- a\n- b\n---\nBody", "taxonomy_contract_violation")
        is None
    )


def test_strategy_that_still_violates_contract_is_rejected(monkeypatch):
    class IncompleteNormalizer:
        def sanitize_tags(self, tags):
            return SimpleNamespace(tags=["still/bad"])

        def validate_tags(self, tags):
            return SimpleNamespace(is_valid=False)

    monkeypatch.setattr(
        "news_collector.validation.publication_repairs.TagNormalizer",
        IncompleteNormalizer,
    )
    assert repair_post_content(POST, "taxonomy_contract_violation") is None


def test_dump_failure_returns_none(monkeypatch):
    def boom(*args, **kwargs):
        raise yaml.YAMLError("cannot dump")

    monkeypatch.setattr(
        "news_collector.validation.publication_repairs.yaml.safe_dump", boom
    )
    assert repair_post_content(POST, "taxonomy_contract_violation") is None


def test_raising_strategy_is_swallowed(monkeypatch):
    import news_collector.validation.publication_repairs as repairs

    def boom(content):
        raise RuntimeError("strategy exploded")

    monkeypatch.setitem(repairs._REPAIRERS, "taxonomy_contract_violation", boom)
    assert repair_post_content(POST, "taxonomy_contract_violation") is None
