"""Plan 175 Phase B: generated JSON Schema <-> Pydantic parity.

The neutral artifact is generated in the frontend from
``postStructuralSchema`` (``../noticiencias/src/schemas/post.ts``) and checked
against the shared corpus with Ajv in
``../noticiencias/tests/post-json-schema.test.ts``.  ``jsonschema`` is
deliberately **not** a backend dependency, so this module never executes the
artifact.  It proves the artifact <-> Pydantic direction structurally, by
comparing the artifact with ``AstroPost.model_json_schema()``, and probes the
corpus with Pydantic only.  The artifact <-> corpus direction is pinned by the
frontend Ajv test; together the three layers are covered transitively.

Expectation matrix (authoritative in ``plans/175-json-schema-parity.md``):

* valid and edge fixtures: both sides accept;
* ``invalid/v2-{empty,too-many}-summary-points``: both sides reject
  (structural: the artifact declares ``minItems``/``maxItems``);
* ``invalid/v2-missing-{summary-points,glossary,fact-check,confidence,sources}``:
  the artifact accepts, Pydantic rejects.  These are the named ``superRefine``
  semantic gaps, *not* contract failures;
* ``invalid/v2-missing-why-it-matters``: both sides accept (stale corpus label,
  P0-06/DEC-003);
* calendar-invalid dates and the ``ftp://`` source URL: named divergences.

Structural differences are allowlisted explicitly below.  The comparator
ignores annotations (descriptions/titles/defaults) and compares property names,
required sets, enum values, basic types, nested object/array shapes,
``additionalProperties`` strictness, formats, patterns, and bounds.  Any new
difference fails the test until it is deliberately named here.
"""

from __future__ import annotations

import copy
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from news_collector.contracts.frontend_schema import AstroPost

# ---------------------------------------------------------------------------
# Paths and fixture availability
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FRONTEND_ROOT = _REPO_ROOT.parent / "noticiencias"
_ARTIFACT_PATH = _FRONTEND_ROOT / "src" / "schemas" / "post.schema.json"
_CORPUS_DIR = _FRONTEND_ROOT / "tests" / "fixtures" / "publication-contract-corpus"
_FRONTEND_PARITY_TEST = "../noticiencias/tests/post-json-schema.test.ts"

_JsonSchema = dict[str, Any]


def _ci_expects_frontend() -> bool:
    """True when CI has promised the frontend artifacts and must fail closed."""
    return os.environ.get("CI_EXPECTED_FRONTEND_SCHEMA", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


@pytest.fixture(scope="module", autouse=True)
def _frontend_contract_present() -> None:
    """Skip locally without the sibling repo; fail closed when CI promises it."""
    missing = [path for path in (_ARTIFACT_PATH, _CORPUS_DIR) if not path.exists()]
    if not missing:
        return
    message = (
        f"Frontend contract artifacts are missing: {missing}. "
        "In CI the sparse checkout/copy step in .github/workflows/ci.yml must "
        "provide src/schemas/post.schema.json and "
        "tests/fixtures/publication-contract-corpus/."
    )
    if _ci_expects_frontend():
        pytest.fail(message)
    pytest.skip(message)


def _load(relative_path: str) -> Any:
    """Load a JSON fixture or the artifact (call after the module fixture)."""
    return json.loads((_CORPUS_DIR / relative_path).read_text(encoding="utf-8"))


def _artifact() -> _JsonSchema:
    return json.loads(_ARTIFACT_PATH.read_text(encoding="utf-8"))


def _pydantic_schema() -> _JsonSchema:
    return AstroPost.model_json_schema()


# ---------------------------------------------------------------------------
# Expectation matrix
# ---------------------------------------------------------------------------

_VALID_FIXTURES = (
    "valid/v1-complete.json",
    "valid/v2-complete.json",
    "edge-cases/defaults.json",
    "edge-cases/additional-property-stripped.json",
)

# Structural rejections: the missing/violated constraint is encoded in the
# artifact itself (minItems/maxItems), unlike the superRefine gaps below.
_STRUCTURAL_REJECTIONS = (
    ("invalid/v2-empty-summary-points.json", "summary_points"),
    ("invalid/v2-too-many-summary-points.json", "summary_points"),
)

# Named semantic gaps: the artifact (and the frontend's structural Zod schema)
# accept; only the full posts schema superRefine and Pydantic reject.
_SEMANTIC_GAPS = (
    ("invalid/v2-missing-summary-points.json", "summary_points"),
    ("invalid/v2-missing-glossary.json", "glossary"),
    ("invalid/v2-missing-fact-check.json", "fact_check"),
    ("invalid/v2-missing-confidence.json", "confidence"),
    ("invalid/v2-missing-sources.json", "sources"),
)

# Frozen corpus correction: valid despite living under invalid/ (P0-06/DEC-003).
_STALE_LABEL_FIXTURE = "invalid/v2-missing-why-it-matters.json"

_DATE_FORMAT_VALUES = ("2026-01-15", "2026-01-17", "2026-08-12")
_DERIVED_DATETIME = "2026-08-12T00:00:00Z"
_INVALID_DATES = ("2026-13-40", "not-a-date", "2026-02-30")


def _v2_with(**overrides: Any) -> _JsonSchema:
    data = copy.deepcopy(_load("valid/v2-complete.json"))
    data.update(overrides)
    return data


def _only_field_removed(relative_path: str, field: str) -> _JsonSchema:
    data = _load(relative_path)
    v2 = _load("valid/v2-complete.json")
    assert set(v2) - set(data) == {field}, (
        f"{relative_path} must isolate exactly {field!r}; "
        f"removed={sorted(set(v2) - set(data))}"
    )
    return data


# ---------------------------------------------------------------------------
# Corpus matrix (Pydantic side)
# ---------------------------------------------------------------------------


def test_corpus_inventory_is_fully_classified() -> None:
    """Every corpus file is named by this matrix exactly once."""
    assert sorted(path.name for path in (_CORPUS_DIR / "valid").glob("*.json")) == [
        "v1-complete.json",
        "v2-complete.json",
    ]
    assert sorted(
        path.name for path in (_CORPUS_DIR / "edge-cases").glob("*.json")
    ) == [
        "additional-property-stripped.json",
        "date-formats.json",
        "defaults.json",
        "source-objects.json",
    ]

    structurally = [fixture for fixture, _field in _STRUCTURAL_REJECTIONS]
    semantically = [fixture for fixture, _field in _SEMANTIC_GAPS]
    classified = sorted(structurally + semantically + [_STALE_LABEL_FIXTURE])
    all_invalid = sorted(
        f"invalid/{path.name}" for path in (_CORPUS_DIR / "invalid").glob("*.json")
    )
    assert classified == all_invalid
    assert len(classified) == len(set(classified))


@pytest.mark.parametrize("fixture", _VALID_FIXTURES)
def test_valid_fixture_is_accepted(fixture: str) -> None:
    """The shared corpus valid set is accepted by Pydantic."""
    post = AstroPost.model_validate(_load(fixture))
    assert post.title
    assert post.date is not None


def test_additional_property_is_accepted_and_ignored() -> None:
    """AstroPost has no extra=\"forbid\"; the artifact also allows extras."""
    data = _load("edge-cases/additional-property-stripped.json")
    assert "not_a_real_field" in data
    post = AstroPost.model_validate(data)
    assert "not_a_real_field" not in post.model_dump()

    artifact = _artifact()
    assert artifact.get("additionalProperties") is not False, (
        "the top-level artifact must allow additional properties, matching "
        "Zod's default stripping and Pydantic's extra='ignore'"
    )


@pytest.mark.parametrize("fixture,field", _STRUCTURAL_REJECTIONS)
def test_structurally_invalid_summary_points_are_rejected(
    fixture: str, field: str
) -> None:
    """Artifact and Pydantic both reject the two structural summary-point cases."""
    data = _load(fixture)
    values = data[field]
    artifact_property = _artifact()["properties"][field]
    assert artifact_property["minItems"] == 2
    assert artifact_property["maxItems"] == 5
    assert not 2 <= len(values) <= 5, (
        f"{fixture} must violate the artifact's minItems/maxItems; "
        f"got {len(values)} items"
    )
    with pytest.raises(ValidationError, match=field):
        AstroPost.model_validate(data)


@pytest.mark.parametrize("fixture,field", _SEMANTIC_GAPS)
def test_semantic_gap_is_an_explicit_divergence(fixture: str, field: str) -> None:
    """Artifact accepts; Pydantic rejects. This is the named gap, not a failure."""
    data = _only_field_removed(fixture, field)

    artifact = _artifact()
    assert (
        field in artifact["properties"]
    ), f"{field!r} must be a structural property in the artifact"
    assert field not in artifact.get("required", []), (
        f"{field!r} must be optional in the artifact; otherwise the schema "
        "would reject this fixture structurally and the gap classification "
        f"would be wrong. See {_FRONTEND_PARITY_TEST} (SEMANTIC_ONLY_INVALID)."
    )

    with pytest.raises(ValidationError, match=field):
        AstroPost.model_validate(data)

    # The frontend test pins the same row (SEMANTIC_ONLY_INVALID) and calls it
    # "a named representation gap". Keep both sides of the matrix aligned.


def test_stale_corpus_label_is_accepted_by_both() -> None:
    """P0-06/DEC-003 makes this frozen invalid/ fixture valid on both sides."""
    data = _only_field_removed(_STALE_LABEL_FIXTURE, "why_it_matters")
    AstroPost.model_validate(data)

    artifact = _artifact()
    assert "why_it_matters" in artifact["properties"]
    assert "why_it_matters" not in artifact.get("required", [])


@pytest.mark.parametrize("value", _DATE_FORMAT_VALUES)
def test_edge_date_formats_are_accepted(value: str) -> None:
    """The corpus date-only strings pass Pydantic and the artifact's date branch."""
    AstroPost.model_validate(_v2_with(date=value))
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
    date.fromisoformat(value)  # RFC 3339 full-date, mirrored by format: date


def test_derived_datetime_is_accepted() -> None:
    """A derived UTC datetime passes Pydantic and the artifact's date-time branch."""
    AstroPost.model_validate(_v2_with(date=_DERIVED_DATETIME))
    datetime.fromisoformat(_DERIVED_DATETIME.replace("Z", "+00:00"))

    date_schema = _artifact()["properties"]["date"]
    assert date_schema["oneOf"] == [
        {"format": "date", "type": "string"},
        {"format": "date-time", "type": "string"},
    ]


def test_edge_source_objects_are_accepted() -> None:
    """Both source-object shapes are accepted and structurally required fields match."""
    sources = _load("edge-cases/source-objects.json")
    AstroPost.model_validate(_v2_with(sources=sources))

    artifact_source = _artifact()["properties"]["sources"]["items"]
    assert set(artifact_source["required"]) == {"title", "url"}
    assert {"publisher", "date"} <= set(artifact_source["properties"])


@pytest.mark.parametrize("value", _INVALID_DATES)
def test_calendar_invalid_dates_are_rejected(value: str) -> None:
    """Pydantic rejects non-calendar dates; the frontend Ajv test pins the artifact side."""
    with pytest.raises(ValidationError):
        AstroPost.model_validate(_v2_with(date=value))
    with pytest.raises(ValueError):
        date.fromisoformat(value)


def test_ftp_source_url_is_a_named_divergence() -> None:
    """Pydantic HttpUrl rejects ftp://; the artifact's format: uri accepts it."""
    data = _v2_with()
    data["sources"][0]["url"] = "ftp://example.com/article"

    with pytest.raises(ValidationError) as exc_info:
        AstroPost.model_validate(data)
    assert exc_info.value.errors()[0]["type"] == "url_scheme"

    artifact_url = _artifact()["properties"]["sources"]["items"]["properties"]["url"]
    assert artifact_url == {"format": "uri", "type": "string"}
    assert "pattern" not in artifact_url, (
        "format: uri accepts any scheme; the http(s)-only refinement is not "
        "encoded in the artifact (frontend test pins this named limit)"
    )


# ---------------------------------------------------------------------------
# Structural comparison helpers
# ---------------------------------------------------------------------------

_ANNOTATION_KEYS = frozenset(
    {"description", "title", "default", "examples", "$comment"}
)
_BOUND_KEYS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
    }
)


def _resolve(node: _JsonSchema, defs: dict[str, _JsonSchema]) -> _JsonSchema:
    """Resolve local ``#/$defs/...`` references (Pydantic emits only these)."""
    seen: set[str] = set()
    while "$ref" in node:
        ref = node["$ref"]
        prefix = "#/$defs/"
        assert ref.startswith(prefix), f"unsupported JSON Schema ref: {ref!r}"
        name = ref[len(prefix) :]
        assert name not in seen, f"cyclic $ref: {name}"
        seen.add(name)
        node = defs[name]
    return node


def _union_keyword(node: _JsonSchema) -> str | None:
    for key in ("anyOf", "oneOf"):
        if key in node:
            return key
    return None


def _is_null(node: _JsonSchema, defs: dict[str, _JsonSchema]) -> bool:
    return _resolve(node, defs).get("type") == "null"


def _is_object(node: _JsonSchema) -> bool:
    return node.get("type") == "object" or "properties" in node


def _normalized_pattern(node: _JsonSchema) -> str | None:
    pattern = node.get("pattern")
    # JSON Schema generators escape ``/``; Pydantic emits it bare. The regex is
    # equivalent, so compare the unescaped form.
    return pattern.replace("\\/", "/") if pattern is not None else None


def _canonical(node: _JsonSchema, defs: dict[str, _JsonSchema]) -> tuple[Any, ...]:
    """Order-insensitive structural fingerprint, ignoring annotations and bounds."""
    node = _resolve(node, defs)
    keyword = _union_keyword(node)
    if keyword:
        branches = [branch for branch in node[keyword] if not _is_null(branch, defs)]
        shapes = frozenset(_canonical(branch, defs) for branch in branches)
        if len(shapes) == 1:
            return next(iter(shapes))
        return ("union", shapes)
    if _is_object(node):
        properties = frozenset(
            (name, _canonical(child, defs))
            for name, child in node.get("properties", {}).items()
        )
        return (
            "object",
            properties,
            frozenset(node.get("required", [])),
            node.get("additionalProperties") is False,
        )
    if node.get("type") == "array":
        return ("array", _canonical(node["items"], defs))
    if "enum" in node:
        return ("enum", frozenset(node["enum"]))
    return (
        "leaf",
        node.get("type"),
        node.get("format"),
        _normalized_pattern(node),
    )


def _branches(
    node: _JsonSchema, defs: dict[str, _JsonSchema]
) -> tuple[list[_JsonSchema], bool]:
    """Return non-null union branches and whether a null branch was present."""
    node = _resolve(node, defs)
    keyword = _union_keyword(node)
    if not keyword:
        return [node], False
    raw = node[keyword]
    non_null = [branch for branch in raw if not _is_null(branch, defs)]
    return non_null, len(non_null) != len(raw)


def _branch_signature(
    node: _JsonSchema, defs: dict[str, _JsonSchema]
) -> tuple[Any, ...]:
    node = _resolve(node, defs)
    if _union_keyword(node):
        return ("union",)
    if _is_object(node):
        return ("object",)
    if node.get("type") == "array":
        return ("array",)
    if "enum" in node:
        return ("enum",)
    return (node.get("type"), node.get("format"))


def _branch_label(signature: tuple[Any, ...]) -> str:
    return ":".join(str(part) for part in signature if part is not None)


def _walk_nodes(
    node: _JsonSchema,
    defs: dict[str, _JsonSchema],
    path: str,
    out: dict[str, _JsonSchema],
) -> None:
    """Collect every reachable node by path, unwrapping nullable unions."""
    node = _resolve(node, defs)
    keyword = _union_keyword(node)
    if keyword:
        non_null = [branch for branch in node[keyword] if not _is_null(branch, defs)]
        if len(non_null) == 1:
            _walk_nodes(non_null[0], defs, path, out)
        else:
            for branch in non_null:
                label = _branch_label(_branch_signature(branch, defs))
                _walk_nodes(branch, defs, f"{path}[{label}]", out)
        return
    out[path] = node
    if _is_object(node):
        for name, child in node.get("properties", {}).items():
            child_path = f"{path}.{name}" if path else name
            _walk_nodes(child, defs, child_path, out)
    elif node.get("type") == "array":
        _walk_nodes(node["items"], defs, f"{path}[]", out)


def _node_maps() -> tuple[dict[str, _JsonSchema], dict[str, _JsonSchema]]:
    artifact_nodes: dict[str, _JsonSchema] = {}
    pydantic_nodes: dict[str, _JsonSchema] = {}
    pydantic = _pydantic_schema()
    _walk_nodes(_artifact(), {}, "", artifact_nodes)
    _walk_nodes(pydantic, pydantic["$defs"], "", pydantic_nodes)
    return artifact_nodes, pydantic_nodes


def _compare_maps(
    getter: Any,
    artifact_nodes: dict[str, _JsonSchema],
    pydantic_nodes: dict[str, _JsonSchema],
) -> dict[str, tuple[Any, Any]]:
    artifact_values = {path: getter(node) for path, node in artifact_nodes.items()}
    pydantic_values = {path: getter(node) for path, node in pydantic_nodes.items()}
    return {
        path: (artifact_values.get(path), pydantic_values.get(path))
        for path in set(artifact_values) | set(pydantic_values)
        if artifact_values.get(path) != pydantic_values.get(path)
    }


def _collect_union_and_null_differences(
    artifact: _JsonSchema,
    pydantic: _JsonSchema,
    defs_artifact: dict[str, _JsonSchema],
    defs_pydantic: dict[str, _JsonSchema],
) -> tuple[set[str], set[str]]:
    """Walk both schemas and record union-keyword and nullable-branch differences."""
    union_paths: set[str] = set()
    null_paths: set[str] = set()

    def walk(
        artifact_node: _JsonSchema,
        pydantic_node: _JsonSchema,
        path: str,
    ) -> None:
        artifact_node = _resolve(artifact_node, defs_artifact)
        pydantic_node = _resolve(pydantic_node, defs_pydantic)
        artifact_keyword = _union_keyword(artifact_node)
        pydantic_keyword = _union_keyword(pydantic_node)
        artifact_branches, artifact_null = _branches(artifact_node, defs_artifact)
        pydantic_branches, pydantic_null = _branches(pydantic_node, defs_pydantic)

        if pydantic_null and not artifact_null:
            null_paths.add(path)
        if (
            artifact_keyword
            and pydantic_keyword
            and artifact_keyword != pydantic_keyword
        ):
            union_paths.add(path)

        if len(artifact_branches) == 1 and len(pydantic_branches) == 1:
            same(
                _resolve(artifact_branches[0], defs_artifact),
                _resolve(pydantic_branches[0], defs_pydantic),
                path,
            )
            return

        artifact_groups: dict[tuple[Any, ...], list[_JsonSchema]] = {}
        pydantic_groups: dict[tuple[Any, ...], list[_JsonSchema]] = {}
        for branch in artifact_branches:
            artifact_groups.setdefault(
                _branch_signature(branch, defs_artifact), []
            ).append(branch)
        for branch in pydantic_branches:
            pydantic_groups.setdefault(
                _branch_signature(branch, defs_pydantic), []
            ).append(branch)

        for signature in sorted(set(artifact_groups) & set(pydantic_groups), key=str):
            artifact_group = sorted(
                artifact_groups[signature],
                key=lambda branch: repr(_canonical(branch, defs_artifact)),
            )
            pydantic_group = sorted(
                pydantic_groups[signature],
                key=lambda branch: repr(_canonical(branch, defs_pydantic)),
            )
            if len(artifact_group) != len(pydantic_group):
                continue
            for artifact_branch, pydantic_branch in zip(
                artifact_group, pydantic_group, strict=True
            ):
                same(
                    _resolve(artifact_branch, defs_artifact),
                    _resolve(pydantic_branch, defs_pydantic),
                    f"{path}[{_branch_label(signature)}]",
                )

    def same(artifact_node: _JsonSchema, pydantic_node: _JsonSchema, path: str) -> None:
        if _union_keyword(artifact_node) or _union_keyword(pydantic_node):
            walk(artifact_node, pydantic_node, path)
            return
        if _is_object(artifact_node) and _is_object(pydantic_node):
            artifact_properties = artifact_node.get("properties", {})
            pydantic_properties = pydantic_node.get("properties", {})
            for name in sorted(set(artifact_properties) & set(pydantic_properties)):
                child_path = f"{path}.{name}" if path else name
                walk(artifact_properties[name], pydantic_properties[name], child_path)
            return
        if (
            artifact_node.get("type") == "array"
            and pydantic_node.get("type") == "array"
        ):
            walk(artifact_node["items"], pydantic_node["items"], f"{path}[]")

    walk(artifact, pydantic, "")
    return union_paths, null_paths


# ---------------------------------------------------------------------------
# Explicit structural allowlist
# ---------------------------------------------------------------------------

# The artifact uses oneOf for ``Union[date, datetime]``; Pydantic uses anyOf.
_ALLOWED_UNION_KEYWORD_DIFFERENCES = {
    "date": "artifact oneOf vs Pydantic anyOf for Union[date, datetime]",
}

# Pydantic wraps every Optional field in anyOf[T, null]; the artifact models an
# absent optional property (no null branch). ``social`` is the before-validator
# nuance: AstroPost.social is Optional for schema generation but
# SocialConfig's before-validator rejects an explicit null at runtime.
_ALLOWED_PYDANTIC_NULL_DIFFERENCES = frozenset(
    {
        "confidence",
        "corrected_at",
        "correction_summary",
        "editorial_score",
        "evidence_detail",
        "evidence_subject_type",
        "fact_check",
        "featured_rank",
        "glossary",
        "headlines_variants",
        "headlines_variants.benefit",
        "headlines_variants.question",
        "image[object].alt",
        "image_alt",
        "institution",
        "known_points",
        "open_questions",
        "permalink",
        "publication_status",
        "refinery_id",
        "review_date",
        "review_status",
        "reviewer_name",
        "reviewer_profile_url",
        "reviewer_role",
        "series",
        "social",
        "social.id",
        "source_url",
        "sources",
        "sources[].date",
        "sources[].doi",
        "sources[].publisher",
        "sources[].role",
        "summary_points",
        "translation_method",
        "uncertainty_note",
        "why_it_matters",
    }
)

# Bound keywords are compared separately. These are the only differences:
# Zod's safe-integer/item bounds vs Pydantic, plus Pydantic HttpUrl's RFC 3986
# length bounds. The plan permits "Zod numeric bounds"; each entry is named.
_ALLOWED_BOUND_DIFFERENCES = frozenset(
    {
        ("featured_rank", "maximum"),
        ("image[object].height", "maximum"),
        ("image[object].width", "maximum"),
        ("known_points[]", "minLength"),
        ("open_questions[]", "minLength"),
        ("reviewer_profile_url", "maxLength"),
        ("reviewer_profile_url", "minLength"),
        ("schema_version", "maximum"),
        ("source_url", "maxLength"),
        ("source_url", "minLength"),
        ("sources[].url", "maxLength"),
        ("sources[].url", "minLength"),
        ("summary_points", "maxItems"),
        ("summary_points", "minItems"),
        ("summary_points[]", "minLength"),
        ("why_it_matters[]", "minLength"),
    }
)


# ---------------------------------------------------------------------------
# Structural parity tests
# ---------------------------------------------------------------------------


def test_top_level_property_names_match() -> None:
    artifact = _artifact()
    pydantic = _pydantic_schema()
    assert set(artifact["properties"]) == set(pydantic["properties"])


def test_top_level_required_sets_match() -> None:
    artifact = _artifact()
    pydantic = _pydantic_schema()
    assert set(artifact.get("required", [])) == set(pydantic.get("required", []))
    assert set(artifact["required"]) == {"date", "excerpt", "image", "title"}


def test_nested_shapes_and_required_sets_match() -> None:
    artifact_nodes, pydantic_nodes = _node_maps()
    assert set(artifact_nodes) == set(pydantic_nodes)

    differences = _compare_maps(
        lambda node: (
            tuple(sorted(node.get("required", []))) if _is_object(node) else None
        ),
        artifact_nodes,
        pydantic_nodes,
    )
    assert differences == {}


def test_enum_sets_match() -> None:
    artifact_nodes, pydantic_nodes = _node_maps()
    differences = _compare_maps(
        lambda node: frozenset(node["enum"]) if "enum" in node else None,
        artifact_nodes,
        pydantic_nodes,
    )
    assert differences == {}

    enums = {
        path: frozenset(node["enum"])
        for path, node in artifact_nodes.items()
        if "enum" in node
    }
    assert enums == {
        "evidence_subject_type": frozenset(
            {
                "humans",
                "animals",
                "in_vitro",
                "computational",
                "observational",
                "experimental",
                "mixed",
                "unknown",
            }
        ),
        "publication_status": frozenset(
            {"peer_reviewed", "preprint", "conference", "other"}
        ),
        "sources[].role": frozenset({"primary", "secondary"}),
    }


def test_basic_types_match() -> None:
    artifact_nodes, pydantic_nodes = _node_maps()
    differences = _compare_maps(
        lambda node: node.get("type"),
        artifact_nodes,
        pydantic_nodes,
    )
    assert differences == {}


def test_formats_and_patterns_match() -> None:
    artifact_nodes, pydantic_nodes = _node_maps()
    format_differences = _compare_maps(
        lambda node: node.get("format"), artifact_nodes, pydantic_nodes
    )
    pattern_differences = _compare_maps(
        _normalized_pattern, artifact_nodes, pydantic_nodes
    )
    assert format_differences == {}
    assert pattern_differences == {}


def test_social_is_strict_and_top_level_extras_are_allowed() -> None:
    artifact = _artifact()
    pydantic = _pydantic_schema()
    pydantic_defs = pydantic["$defs"]

    artifact_social = _resolve(artifact["properties"]["social"], {})
    pydantic_social = _resolve(pydantic["properties"]["social"], pydantic_defs)
    # Pydantic wraps social in anyOf[social, null]; resolve through the branch.
    pydantic_social_branches, _ = _branches(pydantic_social, pydantic_defs)
    assert len(pydantic_social_branches) == 1
    pydantic_social_object = _resolve(pydantic_social_branches[0], pydantic_defs)

    assert artifact_social["additionalProperties"] is False
    assert pydantic_social_object["additionalProperties"] is False
    assert artifact.get("additionalProperties") is not False
    assert pydantic.get("additionalProperties") is not False


def test_structural_fingerprints_match() -> None:
    artifact = _artifact()
    pydantic = _pydantic_schema()
    assert _canonical(artifact, {}) == _canonical(pydantic, pydantic["$defs"])


def test_only_allowlisted_union_and_null_differences_remain() -> None:
    artifact = _artifact()
    pydantic = _pydantic_schema()
    union_paths, null_paths = _collect_union_and_null_differences(
        artifact, pydantic, {}, pydantic["$defs"]
    )
    assert union_paths == set(_ALLOWED_UNION_KEYWORD_DIFFERENCES)
    assert null_paths == set(_ALLOWED_PYDANTIC_NULL_DIFFERENCES)
    assert len(null_paths) == 38


def test_only_allowlisted_bound_differences_remain() -> None:
    artifact_nodes, pydantic_nodes = _node_maps()
    actual: set[tuple[str, str]] = set()
    for path in set(artifact_nodes) | set(pydantic_nodes):
        artifact_bounds = {
            key: value
            for key, value in artifact_nodes.get(path, {}).items()
            if key in _BOUND_KEYS
        }
        pydantic_bounds = {
            key: value
            for key, value in pydantic_nodes.get(path, {}).items()
            if key in _BOUND_KEYS
        }
        for key in set(artifact_bounds) | set(pydantic_bounds):
            if artifact_bounds.get(key) != pydantic_bounds.get(key):
                actual.add((path, key))
    assert actual == set(_ALLOWED_BOUND_DIFFERENCES)


def test_annotations_are_the_only_ignored_keywords() -> None:
    """Keep the ignore list honest: no structural keyword may hide in it."""
    assert _ANNOTATION_KEYS == {
        "description",
        "title",
        "default",
        "examples",
        "$comment",
    }
    assert not (_ANNOTATION_KEYS & _BOUND_KEYS)
    # The fingerprint comparator reads these structural keywords explicitly.
    structural = {
        "type",
        "properties",
        "required",
        "items",
        "enum",
        "format",
        "pattern",
        "additionalProperties",
        "anyOf",
        "oneOf",
        "$ref",
        "$defs",
    }
    assert not (_ANNOTATION_KEYS & structural)
