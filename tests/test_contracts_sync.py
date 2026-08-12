"""
Contract synchronisation tests between the Python Pydantic model and the
TypeScript Zod schema in the sibling front-end repo.

Tests in this file cover two distinct concerns:

1. test_astro_post_serialization — verifies that AstroPost produces valid,
   correctly-typed YAML output and enforces its own validation constraints.

2. test_frontend_schema_field_parity — verifies that the set of top-level field
   names defined in AstroPost matches the set defined in
   ``../noticiencias/src/content.config.ts``.  This test is the mechanical gate
   for the cross-repo contract described in docs/PIPELINE_CONTRACTS.md and
   frontend ADR-0003.

   In CI the front-end content.config.ts is checked out via a sparse
   checkout step; see .github/workflows/ci.yml.  The test fails closed when
   CI_EXPECTED_FRONTEND_SCHEMA is set and the file is missing.  In local
   development the test is skipped when the front-end sibling is absent.
"""

import os
import re
from datetime import date
from pathlib import Path

import pytest
import yaml

from news_collector.contracts.frontend_schema import AstroPost, HeadlinesVariants

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

# Canonical sibling-repo path.  Works whether the cwd is the repo root or any
# subdirectory, as long as both repos share the same parent directory.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_FRONTEND_CONFIG = _REPO_ROOT.parent / "noticiencias" / "src" / "content.config.ts"

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

_ZOD_FIELD_RE = re.compile(
    r"^\s{6}(\w+)\s*:\s*z(?:\.[^\n]+|\s*$)",
    re.MULTILINE,
)


def _extract_zod_fields(ts_source: str) -> set[str]:
    """Return the set of top-level field names from the Zod schema object literal.

    Matches lines of the form ``        fieldName: z.something(`` inside the
    ``z.object({ ... })`` block.  The 8-space indent is the exact indentation
    used in src/content.config.ts and is validated by the CI formatter.
    """
    return set(_ZOD_FIELD_RE.findall(ts_source))


def _resolve_frontend_config() -> Path:
    """Return the expected path; does NOT test existence."""
    return _FRONTEND_CONFIG


def _is_ci_with_expected_schema() -> bool:
    """True when CI has promised a frontend schema and the test must fail closed."""
    return os.environ.get("CI_EXPECTED_FRONTEND_SCHEMA", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_astro_post_serialization():
    """AstroPost serialises to valid YAML and enforces its validation constraints."""

    post = AstroPost(
        title="Test Title",
        excerpt="This is a test excerpt that is long enough.",
        date=date(2023, 1, 1),
        categories=["Ciencia"],
        tags=["tag1", "tag2"],
        image="http://example.com/image.jpg",
        image_alt="Imagen editorial de prueba",
        source_url="http://source.com",
        refinery_id="123456",
        headlines_variants=HeadlinesVariants(question="Q?", benefit="B"),
    )

    model_dict = post.model_dump(exclude_none=True)
    yaml_output = yaml.dump(model_dict, sort_keys=False)

    assert "title: Test Title" in yaml_output
    assert "schema_version: 1" in yaml_output  # Default
    assert (
        "refinery_id: '123456'" in yaml_output
        or 'refinery_id: "123456"' in yaml_output
        or "refinery_id: 123456" in yaml_output
    )

    # Validation constraints must be enforced
    with pytest.raises(ValueError):
        AstroPost(title="Short", excerpt="Short", date=date(2023, 1, 1))  # Too short


def test_frontend_schema_is_available_in_ci():
    """In CI the frontend schema copy step must succeed before parity runs."""
    if not _is_ci_with_expected_schema():
        pytest.skip("Not running in CI with EXPECTED_FRONTEND_SCHEMA set")
    assert _FRONTEND_CONFIG.exists(), (
        f"CI promised a frontend schema at {_FRONTEND_CONFIG} but the file is missing. "
        "Check the sparse-checkout and copy step in .github/workflows/ci.yml."
    )


def test_frontend_schema_field_parity():
    """AstroPost field names must match the top-level fields in content.config.ts.

    This test is the mechanical enforcement gate for the cross-repo contract
    described in docs/PIPELINE_CONTRACTS.md §Frontend Publication Contract and
    in the front-end ADR-0003.

    If this test fails:
    - A field was added to config.ts but not to AstroPost  →  update
      news_collector/contracts/frontend_schema.py.
    - A field was added to AstroPost but not to config.ts  →  update
      src/content.config.ts in the front-end repo.
    - Either change is a cross-repo contract event; follow the migration policy
      in ADR-0003 (bump schema_version, backfill, coordinated deploy).
    """
    if _is_ci_with_expected_schema():
        assert _FRONTEND_CONFIG.exists(), (
            f"CI_EXPECTED_FRONTEND_SCHEMA is set but {_FRONTEND_CONFIG} is missing. "
            "Verify the sparse checkout and copy step in ci.yml."
        )
    elif not _FRONTEND_CONFIG.exists():
        pytest.skip(
            f"Front-end repo not found at expected sibling path "
            f"({_FRONTEND_CONFIG}).  "
            "In CI this test requires the front-end content.config.ts to be "
            "checked out; see .github/workflows/ci.yml for the sparse-checkout step."
        )

    ts_source = _FRONTEND_CONFIG.read_text(encoding="utf-8")
    zod_fields = _extract_zod_fields(ts_source)

    assert zod_fields, (
        f"No Zod fields extracted from {_FRONTEND_CONFIG}. "
        "The regex may need updating if the file indentation changed."
    )

    pydantic_fields = set(AstroPost.model_fields.keys())

    missing_in_pydantic = zod_fields - pydantic_fields
    missing_in_zod = pydantic_fields - zod_fields

    assert not missing_in_pydantic, (
        f"Fields present in content.config.ts but missing from AstroPost: "
        f"{sorted(missing_in_pydantic)}.  "
        "Update news_collector/contracts/frontend_schema.py."
    )
    assert not missing_in_zod, (
        f"Fields present in AstroPost but missing from content.config.ts: "
        f"{sorted(missing_in_zod)}.  "
        "Update ../noticiencias/src/content.config.ts."
    )


def test_frontend_schema_field_parity_missing_in_ci_fails():
    """When CI promises a schema the parity test must NOT skip."""
    if not _is_ci_with_expected_schema():
        pytest.skip("Not running in CI with EXPECTED_FRONTEND_SCHEMA set")
    assert (
        _FRONTEND_CONFIG.exists()
    ), f"CI promised a frontend schema at {_FRONTEND_CONFIG} but the file is absent."


if __name__ == "__main__":
    # fast manual run without pytest
    try:
        test_astro_post_serialization()
        print("✅ AstroPost serialization test passed")
    except Exception as exc:
        print(f"❌ AstroPost serialization test failed: {exc}")
        raise SystemExit(1) from exc

    if _FRONTEND_CONFIG.exists():
        try:
            test_frontend_schema_field_parity()
            print("✅ Cross-repo field parity test passed")
        except Exception as exc:
            print(f"❌ Cross-repo field parity test failed: {exc}")
            raise SystemExit(1) from exc
    else:
        print(f"⚠️  Skipped cross-repo parity check — {_FRONTEND_CONFIG} not found")
