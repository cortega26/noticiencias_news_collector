"""
Module role: Typed final publication artifact stage for `EditorAgent`
(plan 060 Phase 7c-4).

Owns:
- GeneratedArticleValidationError: typed publication-gate failures + codes
- _capability_overclaim_block: plan-111 health-scope escalation
- PublicationArtifactInput / PublicationArtifactHooks / PublicationArtifact
- run_publication_artifact_stage: frontmatter build, publication gates and
  Markdown serialization

Does NOT own:
- Headline/enrichment/fact-check generation (EditorAgent LLM stages)
- Frontmatter YAML normalization, source-identity comment and emoji stripping
  (EditorAgent hooks)
- Provider/model provenance (deferred until a consumer exists)
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import yaml
from pydantic import ValidationError

from news_collector.editorial.health_scope import is_health_scope
from news_collector.editorial.hero_alt import resolve_hero_alt_text
from news_collector.editorial.uncertainty import (
    find_unvalidated_capability_claims,
    resolve_uncertainty_counterweight,
)
from news_collector.utils.logger import get_logger

# Same logger name as the pre-extraction call site so observability output is
# byte-identical after the move (plan 060 Phase 7c-4).
logger = get_logger().create_module_logger("components.editorial.ai_editor")


class GeneratedArticleValidationError(ValueError):
    """Raised when the generated article body is not publishable."""

    def __init__(
        self, message: str, *, error_code: str = "editorial_placeholder_blocked"
    ):
        super().__init__(message)
        self.error_code = error_code


def _capability_overclaim_block(
    overclaims: list[str],
    *,
    categories: Any = None,
    raw_category: Any = None,
    metadata_category: Any = None,
    claim_text: Any = None,
) -> str | None:
    """Health-scope escalation for plan-083 overclaims (plan 111).

    Returns the block message when publication must stop, else None.
    Outside health scope the caller keeps the advisory warning; inside
    health scope an unvalidated present-tense clinical-capability claim
    is a patient-safety-grade defect. Pure: no I/O, fully unit-testable —
    the inline call site only raises on a non-None return.
    """
    if not overclaims:
        return None
    if not is_health_scope(
        categories=categories,
        category=raw_category,
        metadata_category=metadata_category,
        text=claim_text,
    ):
        return None
    return (
        "Unvalidated clinical-capability claim(s) in health scope — "
        "reframe as prospective before publication: " + " | ".join(overclaims)
    )


@dataclass(frozen=True)
class PublicationArtifactInput:
    """Typed inputs of the final publication artifact stage."""

    final_content: str
    headlines: dict[str, Any]
    enrichment_fields: dict[str, Any]
    verified_fact_check: list[Any]
    raw_text: str | dict
    override_date: str | None
    article_id: str
    title: str
    final_category: str
    raw_category: str
    metadata_category: str | None
    image_url: str | None
    image_alt: str | None
    source_id: str | None
    source_name: str | None
    source_url: str | None
    required_enrichment_fields: tuple[str, ...]


@dataclass(frozen=True)
class PublicationArtifactHooks:
    """EditorAgent collaborators the stage drives."""

    normalize_frontmatter: Callable[[dict[str, Any]], dict[str, Any]]
    upsert_source_identity: Callable[[str, str | None, str | None], str]
    strip_emojis: Callable[[str], str]


@dataclass(frozen=True)
class PublicationArtifact:
    """Serialized article plus the normalized frontmatter it was built from."""

    markdown: str
    frontmatter: dict[str, Any]


def _sanitize_headline(value: Any, *, list_fallback: str) -> str:
    # Sanitize title/excerpt: ensure it's a string and not a list representation
    if isinstance(value, list):
        value = value[0] if value else list_fallback
    return str(value).replace('"', '\\"')


def _raw_tags(headlines: dict[str, Any], raw_category: str) -> list[Any]:
    raw_tags = headlines.get("tags") or []
    # Fallback if raw_tags is None or empty, use category if not 'other'
    if not raw_tags and raw_category.lower() != "other":
        raw_tags = [raw_category]
    return raw_tags


def _log_tag_validation(normalizer: Any, final_tags: list[Any]) -> None:
    # VALIDATE
    val_result = normalizer.validate_tags(final_tags)
    if val_result.needs_review:
        logger.warning(f"Tags require review: {val_result.errors}")
        # We could add a frontmatter flag 'needs_tag_review: true' here if desired
        # for now, we just log it.


def _log_tag_audit(norm_result: Any) -> None:
    # Audit log
    if any((norm_result.replaced, norm_result.removed, norm_result.merged)):
        logger.info(
            f"Tag Audit: {norm_result.model_dump_json(exclude={'tags', 'warnings'})}"
        )


def _normalize_tags(headlines: dict[str, Any], raw_category: str) -> list[Any]:
    # Sanitize and Validate Tags (Repo-Truth Implementation)
    try:
        from news_collector.taxonomy.normalizer import TagNormalizer

        normalizer = TagNormalizer()

        # SANITIZE
        norm_result = normalizer.sanitize_tags(_raw_tags(headlines, raw_category))
        final_tags = norm_result.tags

        _log_tag_validation(normalizer, final_tags)
        _log_tag_audit(norm_result)

    except Exception as e:
        logger.error(f"Tag Normalization Failed: {e}")
        final_tags = headlines.get("tags") or []  # Fallback to raw
    return final_tags


def _parse_publication_date(override_date: str | None) -> Any:
    # Date parsing for PyYAML type coercion. LAW-B5: the canonical
    # publication date must never fall back to the runtime clock —
    # the caller (RefineryEngine) always passes the deterministically
    # derived canonical_date; a missing date is a wiring bug.
    if not override_date:
        raise ValueError(
            "process_article requires override_date (canonical "
            "publication date); refusing to use the runtime clock "
            "in frontmatter (LAW-B5)."
        )
    date_str = override_date
    parsed_date_val: Any = date_str
    if isinstance(date_str, str):
        from datetime import datetime

        try:
            if len(date_str) == 10:
                parsed_date_val = datetime.strptime(date_str, "%Y-%m-%d").date()
            else:
                parsed_date_val = datetime.fromisoformat(date_str)
        except ValueError:
            pass
    return parsed_date_val


def _headline_variants(headlines: dict[str, Any]) -> dict[str, str] | None:
    # Prepare optional fields
    if headlines and headlines.get("question") and headlines.get("benefit"):
        return {
            "question": headlines.get("question", ""),
            "benefit": headlines.get("benefit", ""),
        }
    return None


def _base_frontmatter(
    data: PublicationArtifactInput,
    *,
    final_title: str,
    final_excerpt: str,
    final_tags: list[Any],
    parsed_date: Any,
) -> dict[str, Any]:
    # Categories is a list in schema, but currently single string. Wrap it.
    # Schema expects list[str].
    categories_list = [data.final_category] if data.final_category else []
    return {
        "title": final_title,
        # REVIEW: canonical default is SCHEMA_VERSION=1; is this intentionally 2?
        "schema_version": 2,
        "date": parsed_date,
        "author": "Noticiencias AI",
        "categories": categories_list,
        "tags": final_tags,
        "excerpt": final_excerpt,
    }


def _apply_media_frontmatter(
    model_dict: dict[str, Any],
    data: PublicationArtifactInput,
    *,
    final_title: str,
) -> None:
    if data.image_url:
        model_dict["image"] = data.image_url
    # Hero alt root fix (plan 079): the pre-edit fallback embeds the
    # ENGLISH original title. Recompute boilerplate alts with the
    # Spanish title now that it exists; good brief alts pass through.
    previous_alt = data.image_alt if isinstance(data.image_alt, str) else None
    resolved_alt = resolve_hero_alt_text(data.image_alt, final_title)
    if resolved_alt and resolved_alt != (previous_alt or "").strip():
        logger.info("Hero alt recomputed with the Spanish headline.")
    if resolved_alt:
        model_dict["image_alt"] = resolved_alt
    if data.source_url:
        model_dict["source_url"] = data.source_url


def _apply_identity_frontmatter(
    model_dict: dict[str, Any],
    data: PublicationArtifactInput,
    *,
    hl_variants: dict[str, str] | None,
) -> None:
    if data.article_id and data.article_id != "unknown":
        model_dict["refinery_id"] = data.article_id
    if hl_variants:
        model_dict["headlines_variants"] = hl_variants


_ENRICHMENT_KEYS = (
    "summary_points",
    "glossary",
    "fact_check",
    "why_it_matters",
    "confidence",
    "sources",
)
_PASSTHROUGH_KEYS = (
    "uncertainty_note",
    "featured",
    "featured_rank",
    "investigation",
)


def _apply_generated_enrichment(
    model_dict: dict[str, Any], enrichment_fields: dict[str, Any]
) -> None:
    # V2 Editorial Enrichment Fields (Stage 6 generated).
    # Generated values serve as defaults. Upstream raw_text values
    # take precedence when present (allows pipeline overrides and
    # manual editorial corrections from the Refinery UI).
    for key in _ENRICHMENT_KEYS:
        generated_value = enrichment_fields.get(key)
        if generated_value:
            model_dict[key] = generated_value


def _apply_upstream_enrichment(
    model_dict: dict[str, Any], raw_text: str | dict
) -> None:
    # Upstream raw_text overrides for enrichment fields
    if not isinstance(raw_text, dict):
        return
    for key in _ENRICHMENT_KEYS:
        if key in raw_text and raw_text[key]:
            model_dict[key] = raw_text[key]


def _apply_passthrough_fields(model_dict: dict[str, Any], raw_text: str | dict) -> None:
    # Non-enrichment passthrough fields (not generated by Stage 6)
    if not isinstance(raw_text, dict):
        return
    for key in _PASSTHROUGH_KEYS:
        if key in raw_text:
            model_dict[key] = raw_text[key]


def _apply_enrichment_fields(
    model_dict: dict[str, Any],
    enrichment_fields: dict[str, Any],
    raw_text: str | dict,
) -> None:
    _apply_generated_enrichment(model_dict, enrichment_fields)
    _apply_upstream_enrichment(model_dict, raw_text)
    _apply_passthrough_fields(model_dict, raw_text)


def _overclaim_claim_text(final_title: str, model_dict: dict[str, Any]) -> str:
    return " ".join(
        [
            str(final_title or ""),
            *[
                str(item)
                for item in (model_dict.get("why_it_matters") or [])
                if isinstance(item, str)
            ],
            str((model_dict.get("headlines_variants") or {}).get("benefit", "")),
        ]
    )


def _enforce_overclaim_gate(
    model_dict: dict[str, Any],
    data: PublicationArtifactInput,
    *,
    final_title: str,
    requires_uncertainty_note: bool,
    uncertainty_note: str | None,
) -> None:
    # Flag reader-facing narrative that contradicts that counterweight
    # (plan 083): a post that disclaims clinical validation should not
    # also assert the capability in the present tense in
    # `why_it_matters` / `headlines_variants.benefit`. Advisory by
    # default — the PR reviewer (and the Codex re-review) act on it —
    # except inside health scope, where plan 111 escalates to a
    # hard block below.
    overclaims = find_unvalidated_capability_claims(
        model_dict,
        requires_uncertainty_note=requires_uncertainty_note,
        uncertainty_note=uncertainty_note,
    )
    if not overclaims:
        return
    joined_overclaims = " | ".join(overclaims)
    logger.warning(
        "Present-tense capability claim(s) under a declared "
        "uncertainty counterweight — reframe as prospective before "
        f"merge: {joined_overclaims}"
    )
    # Health-scope escalation (plan 111): outside health scope
    # the warning above stays advisory for the PR reviewer.
    # Inside health scope (clinical categories or trigger
    # vocabulary in the claim-bearing fields) an unvalidated
    # present-tense capability claim is a patient-safety-grade
    # defect — block publication until reframed as prospective.
    # The universal verifier-disputed gate below is untouched.
    block_message = _capability_overclaim_block(
        overclaims,
        categories=model_dict.get("categories"),
        raw_category=data.raw_category,
        metadata_category=data.metadata_category,
        claim_text=_overclaim_claim_text(final_title, model_dict),
    )
    if block_message is not None:
        raise GeneratedArticleValidationError(
            block_message,
            error_code="editorial_capability_overclaim",
        )


def _enforce_v2_completeness_gate(
    model_dict: dict[str, Any],
    required_enrichment_fields: tuple[str, ...],
) -> None:
    # V2 contract enforcement: a schema_version >= 2 article MUST
    # carry every enrichment field.  Omission means Stage 6 produced
    # empty or invalid output — treat as retryable editorial failure.
    schema_ver = model_dict.get("schema_version", 1)
    if isinstance(schema_ver, int) and schema_ver >= 2:
        missing = [k for k in required_enrichment_fields if not model_dict.get(k)]
        if missing:
            raise GeneratedArticleValidationError(
                f"V2 article missing required enrichment fields: {missing}. "
                "Stage 6 output is incomplete; retry or supply fields manually.",
                error_code="editorial_v2_incomplete",
            )


def _enforce_fact_check_gate(verified_fact_check: list[Any]) -> None:
    # Fact-check gate (Phase 2c): block publication only on a claim
    # the independent verifier (Stage 7, above) actually returned
    # as "disputed" — i.e. the verifier compared the claim against
    # the article's own source content and found a contradiction.
    # Deliberately reads `verified_fact_check` (the verifier's own
    # output), not `model_dict["fact_check"]`: the latter can be
    # replaced by an upstream `raw_text["fact_check"]` manual
    # override (see the "Upstream raw_text overrides" loop above),
    # which never goes through verification — gating on model_dict
    # would let an un-verified self-assessed "disputed" (or an
    # operator's manual override) trigger this block, exactly the
    # false-positive Design §2's overwrite-all rule exists to
    # prevent. "uncertain" is advisory only and never blocks.
    disputed_labels = [
        str(item.get("label", "")).strip() or "(sin descripción)"
        for item in verified_fact_check
        if isinstance(item, dict) and item.get("status") == "disputed"
    ]
    if disputed_labels:
        raise GeneratedArticleValidationError(
            "Fact-check verification disputed the following claim(s) "
            f"against the article's own source content: {disputed_labels}. "
            "Publication blocked pending correction.",
            error_code="editorial_fact_check_disputed",
        )


def _serialize_article(
    model_dict: dict[str, Any],
    hooks: PublicationArtifactHooks,
    final_content: str,
) -> tuple[dict[str, Any], str]:
    # Dump to YAML
    # Use python mode to preserve native date types and emit
    # YAML date tokens without quotes for Astro z.date() compatibility.
    model_dict = hooks.normalize_frontmatter(model_dict)

    # Custom dumper to ensure correct formatting (e.g. no aliases)
    # Safe dump usually avoids complex tags
    yaml_frontmatter = yaml.safe_dump(
        model_dict,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=1000,  # Avoid wrapping long lines unnecessarily
    ).strip()

    # Prepare full article
    return model_dict, f"---\n{yaml_frontmatter}\n---\n\n{final_content}"


def _strip_tldr_visual(full_article: str) -> str:
    # Regex to remove **TL;DR Visual**... up to next **Header** or end of string
    # Using DOTALL to match newlines
    return re.sub(
        r"\*\*TL;DR Visual\*\*.*?(?=\*\*|$)",
        "",
        full_article,
        flags=re.DOTALL | re.MULTILINE,
    )


def _apply_uncertainty_counterweight(
    model_dict: dict[str, Any], headlines: dict[str, Any]
) -> tuple[bool, str | None]:
    requires_uncertainty_note, uncertainty_note = resolve_uncertainty_counterweight(
        headlines, model_dict.get("confidence")
    )
    model_dict["requires_uncertainty_note"] = requires_uncertainty_note
    if uncertainty_note:
        model_dict["uncertainty_note"] = uncertainty_note
    return requires_uncertainty_note, uncertainty_note


def _finalize_article(
    full_article: str,
    data: PublicationArtifactInput,
    hooks: PublicationArtifactHooks,
) -> str:
    # Persist source identity metadata as a hidden comment to keep provenance
    # without widening the frontmatter schema contract.
    full_article = hooks.upsert_source_identity(
        full_article, data.source_id, data.source_name
    )
    # Logic to strip Visual planning section if no image is present (Rule from tests)
    if not data.image_url:
        full_article = _strip_tldr_visual(full_article)
    return hooks.strip_emojis(full_article)


def run_publication_artifact_stage(
    data: PublicationArtifactInput,
    hooks: PublicationArtifactHooks,
) -> PublicationArtifact:
    """Build, gate and serialize the final publication artifact.

    Verbatim move of the `# 3. Assemble Final Artifact` block previously
    inlined in `EditorAgent.process_article` (plan 060 Phase 7c-4), split
    into pure helpers: same serialization bytes, gate order, messages and
    failure codes.
    """
    final_title = _sanitize_headline(
        data.headlines.get("direct", data.title), list_fallback="Untitled"
    )
    final_excerpt = _sanitize_headline(
        data.headlines.get("excerpt", ""), list_fallback=""
    )
    final_tags = _normalize_tags(data.headlines, data.raw_category)

    model_dict: dict[str, Any] = {}
    # Construct Frontmatter using Strict Contract
    try:
        model_dict = _base_frontmatter(
            data,
            final_title=final_title,
            final_excerpt=final_excerpt,
            final_tags=final_tags,
            parsed_date=_parse_publication_date(data.override_date),
        )
        _apply_media_frontmatter(model_dict, data, final_title=final_title)
        _apply_identity_frontmatter(
            model_dict, data, hl_variants=_headline_variants(data.headlines)
        )
        _apply_enrichment_fields(model_dict, data.enrichment_fields, data.raw_text)

        requires_uncertainty_note, uncertainty_note = _apply_uncertainty_counterweight(
            model_dict, data.headlines
        )

        _enforce_overclaim_gate(
            model_dict,
            data,
            final_title=final_title,
            requires_uncertainty_note=requires_uncertainty_note,
            uncertainty_note=uncertainty_note,
        )
        _enforce_v2_completeness_gate(model_dict, data.required_enrichment_fields)
        _enforce_fact_check_gate(data.verified_fact_check)

        model_dict, full_article = _serialize_article(
            model_dict, hooks, data.final_content
        )
    except ValidationError as ve:
        logger.error(f"AstroPost Contract Validation Failed: {ve}")
        # Fallback to manual construction or raise?
        # FAIL CLOSED: Raise error to prevent invalid content
        raise ValueError(f"Content Contract Violation: {ve}") from ve
    except Exception as e:
        logger.error(f"Error generating frontmatter: {e}")
        raise

    return PublicationArtifact(
        markdown=_finalize_article(full_article, data, hooks),
        frontmatter=model_dict,
    )
