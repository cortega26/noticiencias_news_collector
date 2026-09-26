# Plan 060 / Phase 7c-4 — Typed final publication artifact stage

> **Executor instructions**: Follow this spec step by step. Run every
> verification command and confirm the expected result before moving on. If a
> STOP condition triggers, stop and report — do not improvise. When done,
> annotate the Phase 7 `EditorAgent` checkbox in `plans/060/todo.md` (7c-1
> through 7c-4 done; provenance deferred, see below) and validate the plans
> ledger. This is a phase folder under plan 060 — no new ledger row.
>
> **Drift check (run first)**:
> `git diff --stat e1daeaf..HEAD -- news_collector/components/editorial/ tests/unit/editorial/ tests/e2e_editorial_guardrails/`
> If any file changed since this spec was written, re-verify the "Current
> state" line references; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M/L
- **Risk**: MEDIUM (large verbatim move; no serialization, gate, message or
  contract change allowed)
- **Depends on**: 7c-1/7c-2/7c-3
- **Category**: tech-debt / architecture (LAW-B1, LAW-B3, LAW-B9)
- **Planned at**: backend `e1daeaf`, 2026-09-26

## Why this phase exists

Plan 060 Phase 7's editor work ends with the **final publication artifact**
stage: the frontmatter build, the publication gates and the Markdown
serialization currently occupy the last ~300 lines of
`EditorAgent.process_article`. They are the only major block still inlined in
the façade and they combine a typed input set (article identity, headline /
enrichment / fact-check results, editorial context) with a typed outcome
(frontmatter + Markdown) and typed failure codes (`GeneratedArticleValidationError.error_code`:
`editorial_capability_overclaim`, `editorial_v2_incomplete`,
`editorial_fact_check_disputed`).

This slice extracts the block verbatim into a pure stage module with typed
input/output/hooks, so the façade ends with one declared call and the stage is
unit-testable without an `EditorAgent` or network. `EditorAgent` keeps its
prompt/LLM/generation responsibilities and still re-exports the moved public
symbols for existing importers.

### Provider/model provenance (deferred, documented)

The plan's per-stage declaration list also mentions provider/model
provenance. The LLM stages were typed in 7c-2/7c-3; the final artifact stage
performs **no LLM call** (it is deterministic serialization + gates), so
provenance does not belong to it. Capturing provenance on the LLM stages
would add state with no consumer today: `_send_prompt` already logs provider
and model, and `llm_run_stats`/`llm_run_report` aggregate counts per phase,
not per-model. Per LAW-B9 the capture is deferred until a consumer exists
(e.g. a per-stage model report); the plan tracker records this explicitly
instead of shipping dead plumbing.

## Current state (verified at `e1daeaf`)

- `ai_editor.py:2457-2757` — `# 3. Assemble Final Artifact` through
  `return self._strip_emojis(full_article)` (one block):
  - headline/excerpt selection + `"` escaping; tag normalization inside a
    `try/except Exception` (local `TagNormalizer` import) with
    `Tag Normalization Failed` error + raw fallback;
  - frontmatter build inside a `try` with `override_date` enforcement
    (LAW-B5 error text), date parsing, `model_dict` construction
    (`schema_version: 2`, author, categories, tags, excerpt), image /
    `resolve_hero_alt_text` / source_url / `refinery_id` / headline variants;
  - Stage 6 enrichment values then upstream `raw_text` overrides then
    non-enrichment passthrough (`uncertainty_note`, `featured`,
    `featured_rank`, `investigation`);
  - `resolve_uncertainty_counterweight`; plan-083 overclaim warning +
    plan-111 `_capability_overclaim_block` health-scope hard block;
  - V2 required-enrichment gate; Phase 2c disputed fact-check gate;
  - `self._normalize_frontmatter_for_yaml` + `yaml.safe_dump` +
    `full_article = f"---\n{yaml_frontmatter}\n---\n\n{final_content}"`;
  - `except ValidationError` → `ValueError("Content Contract Violation: ...")`;
    `except Exception` → log + re-raise;
  - `self._upsert_source_identity_comment`; TL;DR Visual strip when no
    `image_url`; `self._strip_emojis`.
- `ai_editor.py:339-346` — `_V2_REQUIRED_ENRICHMENT_FIELDS` (stays in
  `ai_editor.py`: the Stage 6 cache check still uses it; passed to the stage
  as input).
- `ai_editor.py:358-365` — `GeneratedArticleValidationError` (moves; still
  used by `validate_generated_article_markdown` at `:538` and by tests
  importing it from `ai_editor` — re-export required).
- `ai_editor.py:368-396` — `_capability_overclaim_block` (moves; imported by
  `tests/unit/editorial/test_health_scope.py:9` from `ai_editor` — re-export
  required). Only caller is the moved block.
- `ai_editor.py:31` `is_health_scope` and `:17` top-level `import yaml` are
  used only by moved code (`:765` is a function-local import) → remove from
  `ai_editor.py`, add to the new module.
- Agent methods used by the block: `_normalize_frontmatter_for_yaml` (`:842`),
  `_upsert_source_identity_comment` (`:820`), `_strip_emojis` (`:779`) —
  passed as hooks so `ai_editor.py` keeps them.
- Tests that must keep passing unchanged: `tests/unit/editorial/` +
  `tests/test_editor_agent.py` + `tests/test_ai_editor_tags.py` +
  `tests/test_terminology.py` (baseline 2026-09-26: **434 passed, 1 skipped**)
  plus `tests/e2e_editorial_guardrails/`. `test_generated_article_guardrails.py`
  and `test_health_scope.py` pin the moved gates and import the moved symbols
  from `ai_editor`.

## Scope

**In scope** (the only files to modify):

- NEW `news_collector/components/editorial/editorial_publication_artifact.py`
  — `GeneratedArticleValidationError` (moved), `_capability_overclaim_block`
  (moved), `PublicationArtifactInput`, `PublicationArtifactHooks`,
  `PublicationArtifact`, `run_publication_artifact_stage`.
- `news_collector/components/editorial/ai_editor.py` — remove the moved
  definitions/block; import the stage and re-export the moved public symbols;
  `process_article` ends with the single stage call.
- NEW `tests/unit/editorial/test_editorial_publication_artifact.py`.
- `plans/060/todo.md` annotation only.

**Out of scope** (do NOT touch):

- `_V2_REQUIRED_ENRICHMENT_FIELDS` (stays in `ai_editor.py`).
- `validate_generated_article_markdown`, heading normalization, prompt/LLM
  stages, `_normalize_frontmatter_for_yaml` body, `_upsert_source_identity_comment`
  body, `_strip_emojis` body.
- Provider/model provenance capture (deferred; see above).
- Any serialization, gate, message, logger-message or contract change.
- `docs/ARCHITECTURE.md`.

## Design

### `editorial_publication_artifact.py`

```python
@dataclass(frozen=True)
class PublicationArtifactInput:
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
    normalize_frontmatter: Callable[[dict[str, Any]], dict[str, Any]]
    upsert_source_identity: Callable[[str, str | None, str | None], str]
    strip_emojis: Callable[[str], str]


@dataclass(frozen=True)
class PublicationArtifact:
    markdown: str
    frontmatter: dict[str, Any]


def run_publication_artifact_stage(
    data: PublicationArtifactInput,
    hooks: PublicationArtifactHooks,
) -> PublicationArtifact:
    ...
    return PublicationArtifact(
        markdown=hooks.strip_emojis(full_article),
        frontmatter=model_dict,
    )
```

Rules:

- The body is the **verbatim move** of `ai_editor.py:2457-2757` with only
  these substitutions: `self._normalize_frontmatter_for_yaml` →
  `hooks.normalize_frontmatter`, `self._upsert_source_identity_comment` →
  `hooks.upsert_source_identity`, `self._strip_emojis` → `hooks.strip_emojis`,
  `_V2_REQUIRED_ENRICHMENT_FIELDS` → `data.required_enrichment_fields`, and
  inputs read from `data.*`.
- The local `TagNormalizer` import stays inside the `try` (its ImportError
  fallback behavior is observable).
- The module logger is created as
  `get_logger().create_module_logger("components.editorial.ai_editor")` so the
  module extra and every message stay byte-identical. Loguru's
  `function`/`line` record fields follow the new call frame (inherent to any
  code move; the file handler renders them, messages do not change).
- `GeneratedArticleValidationError` and `_capability_overclaim_block` are
  defined here and re-imported into `ai_editor.py`.
- `ai_editor.py` re-exports the moved names:
  `from ...editorial_publication_artifact import (GeneratedArticleValidationError,
  _capability_overclaim_block, PublicationArtifactHooks,
  PublicationArtifactInput, run_publication_artifact_stage)`.

### `process_article` ending

```python
        # 3. Assemble Final Artifact (typed stage, plan 060 Phase 7c-4)
        artifact = run_publication_artifact_stage(
            PublicationArtifactInput(...all fields...),
            PublicationArtifactHooks(
                normalize_frontmatter=self._normalize_frontmatter_for_yaml,
                upsert_source_identity=self._upsert_source_identity_comment,
                strip_emojis=self._strip_emojis,
            ),
        )
        return artifact.markdown
```

## Test plan

- New `tests/unit/editorial/test_editorial_publication_artifact.py`:
  - happy path: frontmatter carries title/schema_version 2/date/categories,
    enrichment passthrough, `requires_uncertainty_note`, markdown envelope
    (`---` … `---` + body), source-identity hook applied, emoji hook applied.
  - missing `override_date` → `ValueError` with the LAW-B5 canonical-date text.
  - V2-incomplete → `GeneratedArticleValidationError` with
    `error_code == "editorial_v2_incomplete"`.
  - disputed `verified_fact_check` entry → `error_code ==
    "editorial_fact_check_disputed"` (and raw_text override of `fact_check`
    does not trigger it).
  - health-scope overclaim → `error_code == "editorial_capability_overclaim"`.
  - no `image_url` → TL;DR Visual section stripped; with image it survives.
  - upstream `raw_text` enrichment overrides win over generated fields.
- Existing suites unchanged (434 baseline) — `test_generated_article_guardrails.py`,
  `test_health_scope.py`, `test_enrichment_fields.py`,
  `test_fact_check_verification.py` and the e2e guardrails exercise the moved
  gates through `process_article` and the re-exported symbols.

## Steps

### Step 0: Baseline + drift

Run:
`python -m pytest tests/unit/editorial/ tests/test_editor_agent.py tests/test_ai_editor_tags.py tests/test_terminology.py -q`
and the drift check. STOP on non-green or drift.

### Step 1: Tests first

Write `test_editorial_publication_artifact.py` (fails first: module does not
exist).

### Step 2: Module + rewire

Add the module (verbatim move), remove the moved block/definitions from
`ai_editor.py`, add the re-export import, and end `process_article` with the
stage call. Keep `_V2_REQUIRED_ENRICHMENT_FIELDS`, `validate_generated_article_markdown`
and the three hook methods in `ai_editor.py`.

**Verify**: new tests + baseline suites green; `make lint`.

### Step 3: Gates + independent review

`make lint && make type && make test && make test-boundaries`;
`make quality-gate` (snapshot-first); `scripts/validate_plans_ledger.py`.
Run an independent fresh-context review of spec vs implementation (AGENTS
§0.1d) and resolve findings.

**Verify**: all exit 0; `git diff --stat` limited to in-scope files.

## Done criteria (machine-checkable)

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries` exit 0
- [ ] `make quality-gate` snapshots valid
- [ ] `run_publication_artifact_stage` + typed input/hooks/outcome exist;
      `process_article` has a single final-assembly call
- [ ] Existing imports (`GeneratedArticleValidationError`,
      `_capability_overclaim_block` from `ai_editor`) still resolve
- [ ] No existing editor test edited
- [ ] `git diff --name-only` lists only in-scope files
- [ ] `plans/060/todo.md` annotated (7c-1..7c-4 done; provenance deferred with
      rationale); ledger OK

## STOP conditions

Stop and report if:

- Baseline/drift is not clean.
- Any serialization byte, gate order/behavior, error code, message or logger
  name changes.
- The moved block needs a behavior edit to fit (e.g. a missing input field).
- An existing editor test must be modified.
- Any step's verification fails twice after a reasonable fix attempt.

## Git workflow

- Branch: `advisor/060-phase-7c4-publication-artifact`.
- Commit: `refactor(editorial): extract the typed final publication artifact stage`.
- Do NOT push or open a PR unless the operator instructed it.
