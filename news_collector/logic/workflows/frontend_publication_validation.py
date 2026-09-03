"""Backend-driven validation of generated publication artifacts against the frontend."""

from __future__ import annotations

import json
import subprocess  # nosec B404 - deliberate: runs frontend validation commands (no user input in argv)
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence, cast

from news_collector.contracts import MANIFEST_FILENAME
from news_collector.contracts.frontend_schema import AstroPost
from news_collector.contracts.publication_validation import (
    FrontendCheckResult,
    PublicationFailureClass,
    PublicationValidationSummary,
)
from news_collector.editorial.classifier import EditorialClassifier

FIXTURE_ARTICLE_ID = "smoke-test-ci-fixture"
FIXTURE_POST_FILENAME = "_smoke-test.md"

CommandRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]

# --- Production-path fixture generation ------------------------------------
#
# The smoke fixture is produced through the exact same code path a real
# article takes (EditorAgent.process_article), instead of hand-building an
# AstroPost and serializing it. This means the fixture exercises the real
# schema v2 fail-closed gate (GeneratedArticleValidationError /
# "editorial_v2_incomplete") and the real YAML frontmatter assembly, so a
# regression there is caught by this CI fixture instead of only by unit
# tests that call process_article() directly.
#
# The LLM provider is stubbed deterministically (no network calls) following
# the same pattern used by tests/unit/editorial/test_enrichment_fields.py's
# setUp: headline/critic stages are overridden to return fixed values, and
# Stage 4 (editorial enrichment) is exercised for real via a stubbed
# _send_prompt so its own validation/backfill logic runs unmodified.

_FIXTURE_RAW_CONTENT = (
    "Este es el contenido de origen sintético utilizado por el smoke test de "
    "publicación de Noticiencias. Describe, a modo de ejemplo, un hallazgo "
    "científico ficticio sobre el comportamiento de un sistema de prueba bajo "
    "condiciones controladas, con suficiente longitud como para superar el "
    "umbral mínimo de contenido configurado en el backend. El propósito de "
    "este texto no es informar sobre un descubrimiento real, sino ejercitar "
    "el mismo camino de código de producción — traducción, adaptación "
    "editorial, generación de titulares y enriquecimiento editorial — que "
    "procesa cualquier artículo real antes de publicarse en el sitio."
)

_FIXTURE_ARTICLE_BODY = (
    "**Artículo sintético de prueba**\n\n"
    "Este artículo es un fixture generado automáticamente por el smoke test "
    "de publicación del backend de Noticiencias. Su único propósito es "
    "ejercitar, de punta a punta, el mismo camino de ensamblado que produce "
    "un artículo real: traducción científica, adaptación editorial, "
    "generación de titulares con su crítico, y enriquecimiento editorial de "
    "esquema v2 con todos sus campos obligatorios. El contenido no describe "
    "ningún hallazgo real; es deliberadamente sintético y se genera de forma "
    "determinista, sin llamadas a un proveedor de lenguaje real, para que la "
    "validación de publicación sea reproducible en cada ejecución de la "
    "integración continua. Si este archivo llega a aparecer publicado en el "
    "sitio, algo salió mal en el paso de limpieza posterior a la validación."
)

_FIXTURE_HEADLINES = {
    "direct": "Publication Smoke Test Article",
    "question": "¿Sigue funcionando el contrato de publicación v2?",
    "benefit": "Verifica de punta a punta el contrato de publicación.",
    "excerpt": (
        "Artículo sintético generado por el smoke test de publicación para "
        "verificar el contrato de esquema v2 de extremo a extremo."
    ),
    # Explicit, specific tags — without these, process_article falls back to
    # the raw category ("ciencia"), which is on the frontend's stop-tags
    # denylist (scripts/check-tags.js). A stop-tag only produces a lint
    # warning (not a build failure), but a real article's tags always come
    # from the headline stage, never the category fallback, so specific
    # tags here keep the fixture faithful to production shape.
    "tags": ["prueba de publicación", "fixture de integración continua"],
}

# Schema-valid EnrichmentSchema payload (news_collector/components/editorial/
# ai_editor.py:EnrichmentSchema). Individual keys are dropped by
# _enrichment_response_json() to build the missing-field regression variants
# exercised by tests/unit/logic/workflows/test_frontend_publication_validation_fixture.py.
_FIXTURE_ENRICHMENT_PAYLOAD: dict = {
    "summary_points": [
        "Este es un fixture sintético generado por el smoke test de publicación.",
        "Ejercita el mismo camino de código que procesa un artículo real.",
    ],
    "glossary": [
        {
            "term": "Fixture",
            "definition": (
                "Artículo sintético generado deterministamente para validar "
                "el contrato de publicación en integración continua."
            ),
        },
    ],
    "fact_check": [
        {
            "label": "Este artículo es un fixture sintético de CI, no una noticia real.",
            "status": "confirmed",
        },
    ],
    "why_it_matters": [
        (
            "Permite verificar que el pipeline de publicación real produce "
            "contenido que pasa el contrato de esquema v2 antes de que un "
            "artículo real llegue a los mismos gates."
        ),
    ],
    "confidence": "Alta — contenido sintético generado deterministamente para CI.",
    "sources": [
        {
            "title": "Noticiencias CI Smoke Test",
            "url": "https://example.com/smoke-test-ci-fixture-source",
            "publisher": "Noticiencias CI Smoke Test",
            "date": "2026-01-01",
        }
    ],
}


def _fixture_raw_text(*, include_source_metadata: bool = True) -> dict:
    """Build the raw_text dict passed to EditorAgent.process_article().

    Shape matches what process_article expects from a real collected
    article (news_collector/components/editorial/ai_editor.py:1701-1724).

    ``include_source_metadata=False`` omits ``url``/``source_name`` so the
    Stage 4 sources backfill (ai_editor.py:1409-1421) cannot fire — used
    only by the "sources" missing-field regression test, which must prove
    the V2 gate itself rejects an empty sources list rather than relying on
    the backfill to silently paper over it.
    """
    raw_text: dict = {
        "title": "Publication Smoke Test Article",
        "summary": _FIXTURE_RAW_CONTENT,
        "content": _FIXTURE_RAW_CONTENT,
        "image_url": "https://example.com/placeholder.jpg",
        "image_alt": "Smoke test placeholder image",
        "category": "ciencia",
    }
    if include_source_metadata:
        raw_text["url"] = "https://example.com/smoke-test-ci-fixture-source"
        raw_text["source_name"] = "Noticiencias CI Smoke Test"
        raw_text["source_id"] = "smoke-test-ci-fixture-source"
    return raw_text


def _enrichment_response_json(omit_field: str | None = None) -> str:
    """Serialize the fixture's Stage 4 LLM response, optionally omitting
    one field. Omitting (rather than emptying) a key lets Pydantic apply
    its unvalidated default for that one field (news_collector/components/
    editorial/ai_editor.py:EnrichmentSchema — Pydantic v2 does not validate
    defaults), so only that single field ends up empty in the result
    instead of poisoning the whole enrichment payload via a ValidationError
    (which is what an explicit invalid/empty value would do instead)."""
    payload = {
        key: value
        for key, value in _FIXTURE_ENRICHMENT_PAYLOAD.items()
        if key != omit_field
    }
    return json.dumps(payload, ensure_ascii=False)


class _NullCategoryClassifier(EditorialClassifier):
    """Deterministic no-op classifier for CI fixture generation. Always
    declines classification so category resolution falls back to the
    raw/metadata category (matches the stubbing pattern used by
    tests/unit/editorial/test_enrichment_fields.py's setUp)."""

    def __init__(self) -> None:
        # No LLM provider: the fixture never classifies, it always declines.
        pass

    def try_classify_article(
        self,
        title: str,
        summary: str,
        content: str = "",
        *,
        allowed_categories: Sequence[str] | None = None,
        allow_editorial: bool = True,
    ) -> str | None:
        return None


def _build_fixture_editor_agent(*, enrichment_omit_field: str | None = None):
    """Construct a deterministic EditorAgent for CI fixture generation.

    Stubs the LLM provider so every pipeline stage returns fixed,
    schema-valid output — no network calls are made, and the fixture is
    reproducible across runs. Stage 4 (editorial enrichment) is NOT stubbed
    directly: instead, `_send_prompt` is stubbed to return a JSON payload
    for the enrichment call specifically, so EditorAgent's own
    `_generate_enrichment_fields` (schema validation + sources backfill)
    runs for real. This is required for the sources-omission regression
    case to actually exercise the real gate (see _fixture_raw_text).

    Stage 4.5 (Phase 2c fact-check verification) follows the same pattern:
    only its network seam (`_send_fact_check_prompt`, which talks to the
    dedicated `fact_check_provider`) is stubbed, so `_verify_fact_check_claims`
    still runs for real — including the overwrite-all rule and the
    "disputed" gate — against a deterministic "confirmed" verdict, instead
    of making a real Ollama call from this CI fixture.
    """
    from news_collector.components.editorial.ai_editor import EditorAgent

    agent = EditorAgent("http://fixture.invalid", "fixture-model")
    agent.category_resolver._classifier = _NullCategoryClassifier()
    agent._critic_pass = lambda *args, **kwargs: (True, None, True)  # type: ignore[method-assign]
    agent._critic_editorial_pass = lambda *args, **kwargs: (  # type: ignore[method-assign]
        True,
        None,
        True,
    )
    agent._generate_headlines = lambda *args, **kwargs: dict(  # type: ignore[method-assign]
        _FIXTURE_HEADLINES
    )

    enrichment_system_prompt = agent.prompts.get("enrichment", {}).get("system", "")
    enrichment_response = _enrichment_response_json(omit_field=enrichment_omit_field)

    def _stub_send_prompt(
        prompt: str, system: str | None = None, model: str | None = None
    ) -> str:
        if enrichment_system_prompt and system == enrichment_system_prompt:
            return enrichment_response
        return _FIXTURE_ARTICLE_BODY

    agent._send_prompt = _stub_send_prompt  # type: ignore[method-assign]
    agent._send_fact_check_prompt = (  # type: ignore[method-assign]
        lambda prompt, system: {"status": "confirmed"}
    )
    return agent


def render_fixture_markdown(
    *,
    enrichment_omit_field: str | None = None,
    include_source_metadata: bool = True,
) -> str:
    """Render the CI smoke-test fixture through the real production
    assembly path (EditorAgent.process_article), so it exercises exactly
    the same code — including the V2 fail-closed gate — as a real article.

    With no arguments this produces the complete, publishable fixture used
    by `_stage_fixture`/`run_frontend_publication_validation`. The keyword
    arguments exist only for the missing-field regression tests in
    tests/unit/logic/workflows/test_frontend_publication_validation_fixture.py,
    which call this with one enrichment field omitted to prove
    process_article raises GeneratedArticleValidationError
    (error_code="editorial_v2_incomplete") before any writer/Git side
    effect — production callers never pass them.
    """
    with tempfile.TemporaryDirectory(prefix="noticiencias-fixture-cache-") as cache_dir:
        agent = _build_fixture_editor_agent(enrichment_omit_field=enrichment_omit_field)
        agent.cache_dir = Path(cache_dir)
        raw_text = _fixture_raw_text(include_source_metadata=include_source_metadata)
        return cast(
            str,
            agent.process_article(
                raw_text,
                override_date="2026-01-01",
                explicit_article_id=FIXTURE_ARTICLE_ID,
            ),
        )


def _default_command_runner(
    command: Sequence[str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        list(command),
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )


def _classify_failure(
    check_name: str,
    output: str,
) -> PublicationFailureClass:
    lowered = output.lower()
    if (
        "duplicate permalink" in lowered
        or "permalink" in lowered
        and "duplicate" in lowered
    ):
        return "permalink_collision"
    if (
        "[check:tags]" in lowered
        or "tag violations" in lowered
        or "tag contains disallowed" in lowered
        or "categories" in lowered
        or "tags" in lowered
        or "taxonomy" in lowered
    ):
        return "taxonomy_contract_violation"
    if (
        "refinery_manifest" in lowered
        or "published content sidecar check found" in lowered
        or "stale manifest entry" in lowered
        or "escapes posts directory" in lowered
        or "must map to a non-empty filename" in lowered
    ):
        return "sidecar_missing_or_malformed"
    if check_name == "build":
        return "frontend_build_failure"
    if check_name == "test_dist":
        return "frontend_dist_failure"
    if check_name == "test_audit":
        return "frontend_audit_failure"
    return "schema_mismatch"


def _load_manifest(manifest_path: Path) -> tuple[dict[str, str], str | None]:
    if not manifest_path.exists():
        return {}, None
    original_text = manifest_path.read_text(encoding="utf-8")
    parsed = json.loads(original_text)
    if not isinstance(parsed, dict):
        raise ValueError("refinery manifest must be a JSON object")
    normalized = {
        str(key): str(value)
        for key, value in parsed.items()
        if isinstance(key, str) and isinstance(value, str)
    }
    return normalized, original_text


def _stage_fixture(frontend_root: Path) -> dict[str, str | None]:
    posts_dir = frontend_root / "src" / "content" / "posts"
    posts_dir.mkdir(parents=True, exist_ok=True)
    post_path = posts_dir / FIXTURE_POST_FILENAME
    manifest_path = posts_dir / MANIFEST_FILENAME

    manifest, original_manifest_text = _load_manifest(manifest_path)
    manifest[FIXTURE_ARTICLE_ID] = FIXTURE_POST_FILENAME

    post_path.write_text(render_fixture_markdown(), encoding="utf-8")
    manifest_path.write_text(
        f"{json.dumps(manifest, indent=2, sort_keys=True)}\n", encoding="utf-8"
    )

    return {
        "post_path": str(post_path),
        "manifest_path": str(manifest_path),
        "original_manifest_text": original_manifest_text,
    }


def _cleanup_fixture(frontend_root: Path, staged: dict[str, str | None]) -> None:
    post_path = Path(staged["post_path"] or "")
    manifest_path = Path(staged["manifest_path"] or "")
    if post_path.exists():
        post_path.unlink()

    original_manifest_text = staged.get("original_manifest_text")
    if original_manifest_text is None:
        if manifest_path.exists():
            manifest_path.unlink()
        return

    manifest_path.write_text(original_manifest_text, encoding="utf-8")


def _record_check(
    name: str,
    command: Sequence[str],
    cwd: Path,
    runner: CommandRunner,
) -> FrontendCheckResult:
    started = time.perf_counter()
    completed = runner(command, cwd)
    duration = time.perf_counter() - started
    output = f"{completed.stdout}\n{completed.stderr}".strip()
    success = int(completed.returncode) == 0
    return FrontendCheckResult(
        name=name,
        command=" ".join(command),
        success=success,
        returncode=int(completed.returncode),
        duration_seconds=duration,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        failure_class=None if success else _classify_failure(name, output),
    )


def run_frontend_publication_validation(
    frontend_root: Path,
    *,
    summary_output_path: Path | None = None,
    command_runner: CommandRunner | None = None,
    stage_fixture: bool = True,
    post_path: Path | None = None,
    install_dependencies: bool = True,
) -> PublicationValidationSummary:
    runner = command_runner or _default_command_runner
    root = Path(frontend_root).resolve()
    checks: list[FrontendCheckResult] = []
    manifest_path = root / "src" / "content" / "posts" / MANIFEST_FILENAME

    staged: dict[str, str | None]
    cleanup_fixture = False
    if stage_fixture:
        try:
            staged = _stage_fixture(root)
            cleanup_fixture = True
        except Exception as exc:
            summary = PublicationValidationSummary(
                generated_at=datetime.now(timezone.utc).isoformat(),
                frontend_root=str(root),
                post_path=str(
                    root / "src" / "content" / "posts" / FIXTURE_POST_FILENAME
                ),
                manifest_path=str(manifest_path),
                success=False,
                overall_failure_class="sidecar_missing_or_malformed",
                checks=[
                    FrontendCheckResult(
                        name="stage_fixture",
                        command="stage fixture",
                        success=False,
                        returncode=1,
                        stderr=str(exc),
                        failure_class="sidecar_missing_or_malformed",
                    )
                ],
                artifacts={"validation_mode": "fixture"},
            )
            if summary_output_path:
                summary_output_path.parent.mkdir(parents=True, exist_ok=True)
                summary_output_path.write_text(
                    json.dumps(summary.model_dump(mode="json"), indent=2),
                    encoding="utf-8",
                )
            return summary
    else:
        staged = {
            "post_path": str(post_path.resolve()) if post_path else "",
            "manifest_path": str(manifest_path),
            "original_manifest_text": None,
        }

    commands: list[tuple[str, list[str]]] = []
    if install_dependencies:
        # Use --legacy-peer-deps to tolerate transient peer dependency conflicts
        # in the front-end repo's package-lock.json. The smoke test validates the
        # generated post against real front-end gates, not the lockfile's purity.
        commands.append(("npm_ci", ["npm", "ci", "--legacy-peer-deps"]))
    # Generate image derivative manifest entries before lint (which checks them).
    # This ensures new articles with hero images pass check:image-derivatives.
    # Works gracefully without R2 credentials — only produces local manifest entries.
    commands.append(
        (
            "publish_image_derivatives",
            ["npm", "run", "publish:image-derivatives"],
        )
    )
    # Format the post file with Prettier before lint.
    # The LLM-generated markdown may have minor formatting issues.
    post_path_str = staged.get("post_path") or ""
    if post_path_str:
        commands.append(
            (
                "format_post",
                ["npx", "prettier", "--write", post_path_str],
            )
        )
    # Format the entire checkout so that lint's format:check sub-step
    # doesn't fail on pre-existing formatting noise in the front-end repo.
    commands.append(
        (
            "format_repo",
            ["npx", "prettier", "--write", str(root)],
        )
    )
    commands.extend(
        [
            ("lint", ["npm", "run", "lint"]),
            ("validate_content", ["npm", "run", "validate:content"]),
            ("build", ["npm", "run", "build"]),
            ("test_dist", ["npm", "run", "test:dist"]),
            ("test_audit", ["npm", "run", "test:audit"]),
        ]
    )

    overall_failure: PublicationFailureClass | None = None
    try:
        for name, command in commands:
            result = _record_check(name, command, root, runner)
            checks.append(result)
            if not result.success:
                overall_failure = result.failure_class
                break
    finally:
        if cleanup_fixture:
            _cleanup_fixture(root, staged)

    summary = PublicationValidationSummary(
        generated_at=datetime.now(timezone.utc).isoformat(),
        frontend_root=str(root),
        post_path=staged["post_path"] or "",
        manifest_path=staged["manifest_path"] or "",
        success=overall_failure is None,
        overall_failure_class=overall_failure,
        checks=checks,
        artifacts={
            "validation_mode": "fixture" if stage_fixture else "current_state",
            "fixture_article_id": FIXTURE_ARTICLE_ID,
            "fixture_post_filename": FIXTURE_POST_FILENAME,
        },
    )

    if summary_output_path:
        summary_output_path.parent.mkdir(parents=True, exist_ok=True)
        summary_output_path.write_text(
            json.dumps(summary.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )

    return summary


def validate_post_frontmatter_fast(
    post_path: Path,
) -> tuple[bool, PublicationFailureClass | None, str | None]:
    """Fast, dependency-free frontmatter validation of a generated post.

    Parses the post's YAML frontmatter and validates it against the backend
    mirror of the frontend contract (AstroPost) — catching shape violations
    (e.g. ``sources[].date: null``, which the frontend Zod schema rejects)
    in milliseconds, without npm ci / prettier / build.

    Returns (ok, failure_class, error_message). failure_class is
    'taxonomy_contract_violation' for schema violations (the class the
    frontend validation would report), None when the post is valid.
    """
    try:
        text = post_path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, "sidecar_missing_or_malformed", f"cannot read post: {exc}"

    if not text.startswith("---"):
        return (
            False,
            "taxonomy_contract_violation",
            "post does not start with YAML frontmatter",
        )

    parts = text.split("---", 2)
    if len(parts) < 3:
        return (
            False,
            "taxonomy_contract_violation",
            "frontmatter block not closed",
        )

    import yaml

    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        return False, "taxonomy_contract_violation", f"invalid YAML: {exc}"

    if not isinstance(data, dict):
        return False, "taxonomy_contract_violation", "frontmatter is not a mapping"

    # sources[].date must be a string or absent — never null (the frontend
    # Zod schema is z.string().optional(), which rejects explicit null).
    for idx, src in enumerate(data.get("sources") or []):
        if isinstance(src, dict) and src.get("date") is None and "date" in src:
            return (
                False,
                "taxonomy_contract_violation",
                f"sources[{idx}].date is null; omit the key instead (frontend "
                "schema rejects explicit null)",
            )

    try:
        AstroPost.model_validate(data)
    except Exception as exc:  # pydantic ValidationError
        return False, "taxonomy_contract_violation", f"schema violation: {exc}"

    return True, None, None
