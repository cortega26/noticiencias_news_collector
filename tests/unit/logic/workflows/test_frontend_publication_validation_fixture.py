"""Fixture-level characterization of the production-path v2 smoke fixture.

Plan 060 / Phase 2a, Step 3: proves the backend v1 smoke fixture replacement
(frontend_publication_validation.render_fixture_markdown) exercises the same
real fail-closed gate a real article goes through
(news_collector/components/editorial/ai_editor.py:2177-2190,
GeneratedArticleValidationError(error_code="editorial_v2_incomplete")) — for
each of the six V2-required enrichment fields, a variant of the fixture with
that field missing must be rejected before it could ever be staged, and the
complete fixture must succeed and carry every field.
"""

import pytest
import yaml

from news_collector.components.editorial.ai_editor import (
    GeneratedArticleValidationError,
)
from news_collector.logic.workflows.frontend_publication_validation import (
    render_fixture_markdown,
)

_V2_REQUIRED_ENRICHMENT_FIELDS = (
    "summary_points",
    "glossary",
    "fact_check",
    "why_it_matters",
    "confidence",
    "sources",
)


def test_complete_fixture_succeeds_with_all_v2_fields() -> None:
    """The default (no keyword arguments) fixture — the one actually staged
    by _stage_fixture/run_frontend_publication_validation — must produce a
    schema_version: 2 article carrying every required enrichment field."""
    rendered = render_fixture_markdown()

    assert rendered.startswith("---")
    frontmatter = rendered.split("---", 2)[1]
    data = yaml.safe_load(frontmatter)

    assert data["schema_version"] == 2
    for field in _V2_REQUIRED_ENRICHMENT_FIELDS:
        assert data.get(field), f"Missing required v2 field: {field}"


def test_complete_fixture_is_deterministic_across_runs() -> None:
    """The whole point of stubbing the LLM provider (no network calls) is a
    reproducible CI fixture — two independent renders must be byte-identical
    so the smoke test's outcome depends only on the real gates it exercises,
    never on incidental LLM/provider nondeterminism."""
    assert render_fixture_markdown() == render_fixture_markdown()


@pytest.mark.parametrize(
    "field",
    [f for f in _V2_REQUIRED_ENRICHMENT_FIELDS if f != "sources"],
)
def test_fixture_variant_missing_field_fails_closed(field: str) -> None:
    """Stripping any single required enrichment field (via the Stage 4 LLM
    stub omitting that key — not by hand-editing rendered YAML, so this
    exercises EnrichmentSchema validation and the real V2 gate) must raise
    GeneratedArticleValidationError(error_code="editorial_v2_incomplete")
    naming the missing field, before any markdown is produced."""
    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        render_fixture_markdown(enrichment_omit_field=field)

    assert excinfo.value.error_code == "editorial_v2_incomplete"
    assert field in str(excinfo.value)


def test_fixture_variant_missing_sources_fails_closed_without_backfill() -> None:
    """``sources`` is a special case (ai_editor.py:1409-1421): when the
    Stage 4 LLM omits ``sources`` but the raw article input still carries
    ``source_url``/``source_name``, _generate_enrichment_fields
    deterministically backfills a synthetic sources entry from the
    article's own original source — and the missing-field gate never
    fires. That backfill is intentional production behavior; it just means
    a naive "omit sources" variant would silently PASS instead of failing,
    which would prove nothing about the gate.

    To actually exercise the gate for ``sources``, this test also builds
    the fixture's raw input with source_url/source_name both absent
    (include_source_metadata=False) so the backfill has nothing to draw on
    and cannot fire. Do not "fix" this by re-adding source metadata — that
    would defeat the point of the test (see plan 060 phase-2a spec, Step
    3).
    """
    with pytest.raises(GeneratedArticleValidationError) as excinfo:
        render_fixture_markdown(
            enrichment_omit_field="sources", include_source_metadata=False
        )

    assert excinfo.value.error_code == "editorial_v2_incomplete"
    assert "sources" in str(excinfo.value)


def test_fixture_missing_sources_with_source_metadata_backfills_and_succeeds() -> None:
    """Companion/control case for the test above: proves the backfill
    behavior this fixture module relies on for its *default* (complete)
    build actually works as documented — omitting ``sources`` from the
    Stage 4 response while source metadata IS present must NOT fail the
    gate; the backfilled synthetic source satisfies it."""
    rendered = render_fixture_markdown(
        enrichment_omit_field="sources", include_source_metadata=True
    )

    frontmatter = rendered.split("---", 2)[1]
    data = yaml.safe_load(frontmatter)
    assert data.get("sources")
