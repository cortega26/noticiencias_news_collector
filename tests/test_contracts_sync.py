"""
Contract synchronisation tests between the Python Pydantic model and the
TypeScript Zod schema in the sibling front-end repo.

Tests in this file cover two distinct concerns:

1. test_astro_post_serialization — verifies that AstroPost produces valid,
   correctly-typed YAML output and enforces its own validation constraints.

2. test_frontend_schema_field_parity — verifies that the set of top-level field
   names defined in AstroPost matches the set defined by the frontend Zod
   schema.  The schema may be inline in
   ``../noticiencias/src/content.config.ts`` or in a module it imports
   (currently ``src/schemas/post.ts``).  This test is the mechanical gate for
   the cross-repo contract described in docs/PIPELINE_CONTRACTS.md and frontend
   ADR-0003.

   In CI the front-end config and its schema module are checked out via sparse
   checkout steps; see .github/workflows/ci.yml.  The test fails closed when
   CI_EXPECTED_FRONTEND_SCHEMA is set and either file is missing.  In local
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
# Schema resolution and parsing
# ---------------------------------------------------------------------------
#
# The structural schema may live inline in content.config.ts (fixtures and
# legacy configs) or in a module imported by it (frontend plan 174 moved it to
# src/schemas/post.ts).  Resolution is textual on purpose: the gate must not
# execute TypeScript or depend on Node.  Mirrors scripts/check-contract-sync.js
# in the frontend repo.

_TS_MODULE_EXTENSIONS = (".ts", ".tsx", ".mts", ".js", ".mjs")
_MAX_IMPORT_DEPTH = 5

_SCHEMA_INLINE_RE = re.compile(r"\bschema\s*:\s*z\s*\.\s*object\s*\(")
_SCHEMA_IDENTIFIER_RE = re.compile(r"\bschema\s*:\s*([A-Za-z_$][\w$]*)")
_NAMED_IMPORT_RE = re.compile(
    r"\bimport\s+(?:type\s+)?\{([^}]*)\}\s+from\s+['\"]([^'\"]+)['\"]"
)
_DEFAULT_IMPORT_RE = re.compile(
    r"\bimport\s+([A-Za-z_$][\w$]*)\s+from\s+['\"]([^'\"]+)['\"]"
)
_NAMED_REEXPORT_RE = re.compile(
    r"\bexport\s+(?:type\s+)?\{([^}]*)\}\s+from\s+['\"]([^'\"]+)['\"]"
)
_STAR_REEXPORT_RE = re.compile(r"\bexport\s+\*\s+from\s+['\"]([^'\"]+)['\"]")
_ZOD_OBJECT_RE = re.compile(r"\bz\s*\.\s*object\s*\(\s*\{")
_DEFAULT_ZOD_OBJECT_RE = re.compile(r"\bexport\s+default\s+z\s*\.\s*object\s*\(")
_MEMBER_RE = re.compile(r"^([A-Za-z_$][\w$]*)\s*:")


def _find_declaration(source: str, identifier: str) -> int:
    """Return the offset of ``(export )?const <identifier> =`` or -1."""
    match = re.search(
        rf"\b(?:export\s+)?(?:const|let|var)\s+{re.escape(identifier)}\s*[:=]",
        source,
    )
    return match.start() if match else -1


def _is_local_module_specifier(spec: str) -> bool:
    return spec.startswith(("./", "../", "~/"))


def _split_binding_members(raw: str) -> list[tuple[str, str]]:
    """Split ``a, b as c`` import/export braces into (imported, local) pairs."""
    pairs: list[tuple[str, str]] = []
    for part in raw.split(","):
        cleaned = re.sub(r"^type\s+", "", part.strip())
        if not cleaned:
            continue
        pieces = re.split(r"\s+as\s+", cleaned)
        imported = pieces[0].strip()
        local = pieces[-1].strip()
        if imported and local:
            pairs.append((imported, local))
    return pairs


def _parse_module_bindings(source: str) -> list[tuple[str, str, str]]:
    """Return (local, imported, specifier) bindings for named/default/reexports."""
    bindings: list[tuple[str, str, str]] = []

    for match in _NAMED_IMPORT_RE.finditer(source):
        for imported, local in _split_binding_members(match.group(1)):
            bindings.append((local, imported, match.group(2)))

    for match in _DEFAULT_IMPORT_RE.finditer(source):
        bindings.append((match.group(1), "default", match.group(2)))

    for match in _NAMED_REEXPORT_RE.finditer(source):
        for imported, local in _split_binding_members(match.group(1)):
            bindings.append((local, imported, match.group(2)))

    return bindings


def _resolve_module_path(spec: str, from_path: Path, src_root: Path) -> Path | None:
    """Resolve a local TypeScript module specifier to an existing file.

    ``~/`` follows the frontend tsconfig alias (``~/*`` -> ``src/*``), so it
    anchors at ``src_root``; relative specifiers anchor at the importing file.
    """
    if spec.startswith("~/"):
        base = src_root / spec[2:]
    else:
        base = from_path.parent / spec

    candidates = [base]
    candidates.extend(Path(f"{base}{ext}") for ext in _TS_MODULE_EXTENSIONS)
    candidates.extend(base / f"index{ext}" for ext in _TS_MODULE_EXTENSIONS)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _resolve_schema_source(config_path: Path) -> tuple[str, Path]:
    """Return (source, path) holding the Zod ``z.object({...})`` schema.

    Handles the inline form (``schema: z.object(...)``) and the imported module
    form (``schema: <identifier>`` plus a named/default import or re-export).
    Raises ``ValueError`` when the schema or its module cannot be resolved.
    """
    config_path = Path(config_path).resolve()
    try:
        config_source = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(
            f"Cannot read frontend schema config at {config_path}: {exc}"
        ) from exc

    if _SCHEMA_INLINE_RE.search(config_source):
        return config_source, config_path

    identifier_match = _SCHEMA_IDENTIFIER_RE.search(config_source)
    if identifier_match is None:
        raise ValueError(
            "No `schema: z.object(...)` or `schema: <identifier>` declaration "
            f"found in {config_path}."
        )
    identifier = identifier_match.group(1)

    if _find_declaration(config_source, identifier) != -1:
        return config_source, config_path

    src_root = config_path.parent
    current_path = config_path
    current_source = config_source
    visited = {config_path}

    for _ in range(_MAX_IMPORT_DEPTH):
        binding = next(
            (
                (imported, spec)
                for local, imported, spec in _parse_module_bindings(current_source)
                if local == identifier and _is_local_module_specifier(spec)
            ),
            None,
        )
        if binding is None:
            star = _STAR_REEXPORT_RE.search(current_source)
            if star is None:
                break
            binding = ("*", star.group(1))

        imported, spec = binding
        next_path = _resolve_module_path(spec, current_path, src_root)
        if next_path is None:
            raise ValueError(
                f"Cannot resolve schema module '{spec}' imported from "
                f"{current_path} for identifier '{identifier}'."
            )
        if next_path in visited:
            raise ValueError(f"Circular schema module import involving {next_path}.")
        visited.add(next_path)

        try:
            next_source = next_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"Cannot read schema module {next_path}: {exc}") from exc

        if _find_declaration(next_source, identifier) != -1:
            return next_source, next_path
        if imported == "default" and _DEFAULT_ZOD_OBJECT_RE.search(next_source):
            return next_source, next_path

        current_path, current_source = next_path, next_source

    raise ValueError(
        f"Could not resolve the structural schema '{identifier}' from "
        f"{config_path}; expected `(export )?const {identifier} = z.object(...)` "
        "in the config or an imported module."
    )


def _strip_ts_comments(source: str) -> str:
    """Blank ``//`` and ``/* */`` comments while preserving string literals.

    Newlines are preserved so member splitting keeps the same offsets.
    """
    chars = list(source)
    in_string: str | None = None
    i = 0
    while i < len(chars):
        char = chars[i]
        if in_string is not None:
            if char == "\\":
                i += 2
                continue
            if char == in_string:
                in_string = None
            i += 1
            continue
        if char in "'\"`":
            in_string = char
            i += 1
            continue
        if char == "/" and i + 1 < len(chars):
            next_char = chars[i + 1]
            if next_char == "/":
                end = source.find("\n", i)
                if end == -1:
                    end = len(chars)
                for j in range(i, end):
                    chars[j] = " "
                i = end
                continue
            if next_char == "*":
                end = source.find("*/", i + 2)
                if end == -1:
                    end = len(chars) - 2
                for j in range(i, min(end + 2, len(chars))):
                    if chars[j] != "\n":
                        chars[j] = " "
                i = end + 2
                continue
        i += 1
    return "".join(chars)


def _find_top_level_zod_object(source: str) -> int:
    """Return the offset of the first brace-depth-0 ``z.object(`` or -1."""
    depth = 0
    in_string: str | None = None
    i = 0
    while i < len(source):
        char = source[i]
        if in_string is not None:
            if char == "\\":
                i += 2
                continue
            if char == in_string:
                in_string = None
            i += 1
            continue
        if char in "'\"`":
            in_string = char
            i += 1
            continue
        if char == "/" and i + 1 < len(source):
            if source[i + 1] == "/":
                end = source.find("\n", i)
                if end == -1:
                    return -1
                i = end
                continue
            if source[i + 1] == "*":
                end = source.find("*/", i + 2)
                if end == -1:
                    return -1
                i = end + 2
                continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == "z" and depth == 0 and _ZOD_OBJECT_RE.match(source, i):
            return i
        i += 1
    return -1


def _extract_object_body(source: str, start: int) -> str:
    """Return the text between the braces of the ``z.object({...})`` at start."""
    match = _ZOD_OBJECT_RE.search(source, start)
    if match is None:
        raise ValueError("Could not find `z.object({` in the resolved schema source.")

    depth = 0
    in_string: str | None = None
    open_brace = match.end() - 1
    i = open_brace
    while i < len(source):
        char = source[i]
        if in_string is not None:
            if char == "\\":
                i += 2
                continue
            if char == in_string:
                in_string = None
            i += 1
            continue
        if char in "'\"`":
            in_string = char
            i += 1
            continue
        if char == "/" and i + 1 < len(source):
            if source[i + 1] == "/":
                end = source.find("\n", i)
                if end == -1:
                    break
                i = end
                continue
            if source[i + 1] == "*":
                end = source.find("*/", i + 2)
                if end == -1:
                    break
                i = end + 2
                continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[open_brace + 1 : i]
        i += 1

    raise ValueError("Unbalanced braces in the z.object({...}) schema body.")


def _split_top_level_members(body: str) -> list[str]:
    """Split an object body on commas that sit outside nested/string contexts."""
    body = _strip_ts_comments(body)
    members: list[str] = []
    depth = 0
    in_string: str | None = None
    start = 0
    i = 0
    while i < len(body):
        char = body[i]
        if in_string is not None:
            if char == "\\":
                i += 2
                continue
            if char == in_string:
                in_string = None
            i += 1
            continue
        if char in "'\"`":
            in_string = char
            i += 1
            continue
        if char in "{[(":
            depth += 1
        elif char in "}])":
            depth -= 1
        elif char == "," and depth == 0:
            members.append(body[start:i])
            start = i + 1
        i += 1
    members.append(body[start:])
    return members


def _extract_zod_fields(ts_source: str) -> set[str]:
    """Return the top-level field names of the structural Zod object.

    Indentation-agnostic: the object body is located by braces, then split on
    depth-0 commas; each member's leading ``identifier:`` is captured.  Nested
    objects, arrays, strings, and comments cannot contribute fields.
    """
    schema_match = _SCHEMA_INLINE_RE.search(ts_source)
    start = (
        schema_match.start()
        if schema_match is not None
        else _find_top_level_zod_object(ts_source)
    )
    if start == -1:
        raise ValueError("Could not find a `z.object({...})` schema to parse.")

    fields = {
        match.group(1)
        for member in _split_top_level_members(_extract_object_body(ts_source, start))
        if (match := _MEMBER_RE.match(member.strip()))
    }
    if not fields:
        raise ValueError(
            "No Zod fields extracted from the z.object({...}) schema body."
        )
    return fields


def _extract_frontend_fields(config_path: Path) -> set[str]:
    """Resolve the frontend schema (inline or imported) and return its fields."""
    source, _resolved_path = _resolve_schema_source(config_path)
    return _extract_zod_fields(source)


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


def test_wave2_editorial_mirror_fields():
    """Wave 2 (P0-01/P0-02/P0-06): role/doi/evidence fields round-trip.

    Mirrors the frontend schema additions. Legacy payloads without the new
    keys must still validate; malformed DOI and over-long why_it_matters
    must fail closed.
    """
    post = AstroPost(
        title="Test Title for Wave2",
        excerpt="This is a test excerpt that is long enough.",
        date=date(2023, 1, 1),
        image="http://example.com/image.jpg",
        image_alt="Imagen editorial de prueba",
        sources=[
            {
                "title": "Primary paper",
                "url": "https://doi.org/10.1371/journal.pone.0353485",
                "role": "primary",
                "doi": "10.1371/journal.pone.0353485",
            },
            {"title": "Coverage", "url": "http://source.com"},
        ],
        evidence_subject_type="mixed",
        evidence_detail="Cultivo celular y ratones.",
        why_it_matters=["One", "Two", "Three"],
    )
    dumped = post.model_dump(exclude_none=True)
    assert dumped["sources"][0]["role"] == "primary"
    assert dumped["evidence_subject_type"] == "mixed"
    with pytest.raises(ValueError):
        AstroPost(
            title="Test Title for Wave2",
            excerpt="This is a test excerpt that is long enough.",
            date=date(2023, 1, 1),
            image="http://example.com/image.jpg",
            image_alt="Imagen editorial de prueba",
            sources=[{"title": "S", "url": "http://source.com", "doi": "bad"}],
        )

    with pytest.raises(ValueError):
        AstroPost(
            title="Test Title for Wave2",
            excerpt="This is a test excerpt that is long enough.",
            date=date(2023, 1, 1),
            image="http://example.com/image.jpg",
            image_alt="Imagen editorial de prueba",
            why_it_matters=["1", "2", "3", "4"],
        )


def test_wave3_accountability_mirror_fields():
    """Wave 3 (P0-03/P0-09/P2-02/P2-07): accountability fields round-trip.

    All optional; a half-correction must fail closed.
    """
    post = AstroPost(
        title="Test Title for Wave3",
        excerpt="This is a test excerpt that is long enough.",
        date=date(2023, 1, 1),
        image="http://example.com/image.jpg",
        image_alt="Imagen editorial de prueba",
        institution="McGill University",
        publication_status="preprint",
        known_points=["a", "b"],
        open_questions=["c"],
        corrected_at="2026-09-02",
        correction_summary="Se corrigio una cifra.",
    )
    dumped = post.model_dump(exclude_none=True)
    assert dumped["publication_status"] == "preprint"
    assert dumped["corrected_at"] == "2026-09-02"

    with pytest.raises(ValueError):
        AstroPost(
            title="Test Title for Wave3",
            excerpt="This is a test excerpt that is long enough.",
            date=date(2023, 1, 1),
            image="http://example.com/image.jpg",
            image_alt="Imagen editorial de prueba",
            corrected_at="2026-09-02",
        )


def test_frontend_schema_is_available_in_ci():
    """In CI the frontend schema copy step must succeed before parity runs."""
    if not _is_ci_with_expected_schema():
        pytest.skip("Not running in CI with EXPECTED_FRONTEND_SCHEMA set")
    assert _FRONTEND_CONFIG.exists(), (
        f"CI promised a frontend schema at {_FRONTEND_CONFIG} but the file is missing. "
        "Check the sparse-checkout and copy step in .github/workflows/ci.yml."
    )


_INLINE_CONFIG_FIXTURE = """\
import { defineCollection } from 'astro:content';
import { z } from 'astro/zod';

const posts = defineCollection({
  schema: z.object({
      title: z.string().min(5),
      // fake_comment_key: z.string() must never be captured
      excerpt: z.string(),
      image: z.union([
        z.string(),
        z.object({
          src: z.string(),
          alt: z.string().optional(),
        }),
      ]),
      nested_note: z.string().default('nested_key: not a field'),
  }),
});
"""

_MODULE_CONFIG_FIXTURE = """\
import { defineCollection } from 'astro:content';
import { postStructuralSchema } from './schemas/post';

const posts = defineCollection({
  schema: postStructuralSchema.superRefine((data) => data.title),
});
"""

_MODULE_SCHEMA_FIXTURE = """\
import { z } from 'astro/zod';

const SOCIAL_ID_RE = /^[0-9a-f]{64}$/;

export const postStructuralSchema = z.object({
  title: z.string().min(5),
  sources: z
    .array(
      z.object({
        title: z.string(),
        url: z.url(),
      })
    )
    .optional(),
  social: z
    .object({
      publish: z.boolean().default(false),
      id: z.string().regex(SOCIAL_ID_RE).optional(),
    })
    .strict()
    .optional(),
  why_it_matters: z.array(z.string().min(1)).max(3).optional(),
  correction_summary: z.string().min(1).max(500).optional(),
});
"""


def test_extract_inline_schema_fields(tmp_path):
    """The inline schema layout (six-space fields) is parsed by depth, not indent."""
    config_path = tmp_path / "content.config.ts"
    config_path.write_text(_INLINE_CONFIG_FIXTURE, encoding="utf-8")

    source, resolved_path = _resolve_schema_source(config_path)

    assert resolved_path == config_path.resolve()
    assert _extract_zod_fields(source) == {
        "title",
        "excerpt",
        "image",
        "nested_note",
    }


def test_extract_imported_schema_fields(tmp_path):
    """The module layout (two-space fields) resolves the import and parses it."""
    schemas_dir = tmp_path / "schemas"
    schemas_dir.mkdir()
    module_path = schemas_dir / "post.ts"
    module_path.write_text(_MODULE_SCHEMA_FIXTURE, encoding="utf-8")
    config_path = tmp_path / "content.config.ts"
    config_path.write_text(_MODULE_CONFIG_FIXTURE, encoding="utf-8")

    source, resolved_path = _resolve_schema_source(config_path)

    assert resolved_path == module_path.resolve()
    assert _extract_zod_fields(source) == {
        "title",
        "sources",
        "social",
        "why_it_matters",
        "correction_summary",
    }


def test_tilde_alias_schema_import(tmp_path):
    """``~/`` resolves against the frontend ``src/`` root (tsconfig alias)."""
    src_root = tmp_path / "src"
    schemas_dir = src_root / "schemas"
    schemas_dir.mkdir(parents=True)
    module_path = schemas_dir / "post.ts"
    module_path.write_text(_MODULE_SCHEMA_FIXTURE, encoding="utf-8")
    config_path = src_root / "content.config.ts"
    config_path.write_text(
        "import { postStructuralSchema } from '~/schemas/post';\n"
        "const posts = { schema: postStructuralSchema };\n",
        encoding="utf-8",
    )

    source, resolved_path = _resolve_schema_source(config_path)

    assert resolved_path == module_path.resolve()
    assert "title" in _extract_zod_fields(source)


def test_unresolvable_schema_import_raises(tmp_path):
    """A missing imported module raises instead of silently extracting nothing."""
    config_path = tmp_path / "content.config.ts"
    config_path.write_text(
        "import { missingSchema } from './schemas/missing';\n"
        "const posts = { schema: missingSchema };\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Cannot resolve schema module"):
        _resolve_schema_source(config_path)


def test_frontend_schema_field_parity():
    """AstroPost field names must match the frontend Zod schema's top-level fields.

    This test is the mechanical enforcement gate for the cross-repo contract
    described in docs/PIPELINE_CONTRACTS.md §Frontend Publication Contract and
    in the front-end ADR-0003.

    If this test fails:
    - A field was added to the frontend schema but not to AstroPost  →  update
      news_collector/contracts/frontend_schema.py.
    - A field was added to AstroPost but not to the frontend schema  →  update
      src/content.config.ts (or its imported schema module) in the front-end
      repo.
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

    zod_fields = _extract_frontend_fields(_FRONTEND_CONFIG)

    assert zod_fields, (
        f"No Zod fields extracted from the schema referenced by " f"{_FRONTEND_CONFIG}."
    )

    pydantic_fields = set(AstroPost.model_fields.keys())

    missing_in_pydantic = zod_fields - pydantic_fields
    missing_in_zod = pydantic_fields - zod_fields

    assert not missing_in_pydantic, (
        f"Fields present in the frontend Zod schema but missing from AstroPost: "
        f"{sorted(missing_in_pydantic)}.  "
        "Update news_collector/contracts/frontend_schema.py."
    )
    assert not missing_in_zod, (
        f"Fields present in AstroPost but missing from the frontend Zod schema: "
        f"{sorted(missing_in_zod)}.  "
        "Update ../noticiencias/src/content.config.ts or its imported schema module."
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
