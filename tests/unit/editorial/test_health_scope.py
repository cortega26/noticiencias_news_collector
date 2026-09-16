"""Unit tests for health-scope policy + overclaim gate (Plan 111).

Pure policy: no LLM, no DB, no I/O. Proves the single definition of
health scope (shared by the auditor and the pre-PR gate) and the
escalation matrix: empty/advisory/non-health never blocks; health-scope
overclaims block with the exact message.
"""

from news_collector.components.editorial.ai_editor import (
    _capability_overclaim_block,
)
from news_collector.editorial.health_scope import (
    HEALTH_TRIGGER_CATEGORIES,
    HEALTH_TRIGGER_KEYWORDS,
    is_health_scope,
)


def test_trigger_lists_match_auditor_historical_values() -> None:
    assert set(HEALTH_TRIGGER_CATEGORIES) == {
        "health",
        "medicine",
        "biology",
        "salud",
        "biología",
        "medicina",
    }
    assert "cura" in HEALTH_TRIGGER_KEYWORDS
    assert "tratamiento" in HEALTH_TRIGGER_KEYWORDS
    assert len(HEALTH_TRIGGER_KEYWORDS) == 18


def test_category_match_case_insensitive_both_languages() -> None:
    assert is_health_scope(category="Salud")
    assert is_health_scope(category="MEDICINE")
    assert is_health_scope(categories=["Tecnología", "Biología"])
    assert is_health_scope(metadata_category="health")


def test_keyword_match_in_claim_text() -> None:
    assert is_health_scope(text="un nuevo tratamiento experimental")
    assert is_health_scope(categories=["Astronomía"], text="la vacuna reduce")


def test_non_health_scope() -> None:
    assert not is_health_scope(category="Astronomía", text="estrellas y planetas")
    assert not is_health_scope()
    assert not is_health_scope(categories=[])
    assert not is_health_scope(text="   ")


def test_empty_overclaims_never_block() -> None:
    assert (
        _capability_overclaim_block([], categories=["Salud"], claim_text="cura total")
        is None
    )


def test_non_health_overclaims_stay_advisory() -> None:
    assert (
        _capability_overclaim_block(
            ["why_it_matters[0]: El sistema permite anticipar eclipses"],
            categories=["Astronomía"],
            claim_text="permite anticipar eclipses",
        )
        is None
    )


def test_health_category_blocks() -> None:
    message = _capability_overclaim_block(
        ["why_it_matters[0]: El fármaco permite curar la diabetes"],
        categories=["Salud"],
        claim_text="el fármaco permite curar",
    )
    assert message is not None
    assert "health scope" in message


def test_health_keyword_blocks_without_health_category() -> None:
    message = _capability_overclaim_block(
        ["why_it_matters[0]: La terapia permite revertir el cáncer"],
        categories=["Tecnología"],
        claim_text="la terapia permite revertir el cáncer",
    )
    assert message is not None


def test_auditor_keeps_identical_trigger_values() -> None:
    """The auditor must consume the canonical lists (no drift)."""
    import inspect

    from news_collector.components.editorial import auditor as auditor_module

    source = inspect.getsource(auditor_module)
    assert "HEALTH_TRIGGER_KEYWORDS" in source
    assert "HEALTH_TRIGGER_CATEGORIES" in source
