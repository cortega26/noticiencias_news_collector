# Plan 027: Complete Stage 4 model routing and validate its cache

> **Executor instructions**: Keep existing inheritance semantics unless an explicit override is configured. Update plan 027 after focused and config suites pass.
>
> **Drift check (run first)**: `git diff --stat e43bd30..HEAD -- news_collector/infrastructure/llm/model_registry.py noticiencias/config_schema.py noticiencias/config_manager.py apps/refinery/main.py news_collector/components/editorial/ai_editor.py config.toml tests/unit/infrastructure/llm/test_model_registry.py tests/unit/editorial/test_enrichment_fields.py`

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plan 019
- **Category**: bug/tests
- **Planned at**: backend `e43bd30`, 2026-07-21

## Why this matters

The model registry advertises an `enrichment` stage, but strict configuration cannot express its override, legacy environment mapping ignores it, and Refinery drops the resolved value before constructing `EditorAgent`. Valid JSON cache files are reused without schema validation, so a list/scalar/stale shape can crash publication or inject invalid frontmatter.

## Current state

- `model_registry.py:23-47` registers `enrichment → ollama.enrichment_model`.
- `config_schema.py:678-718` permits only base/translator/editor/headlines model fields.
- `config_manager.py:403-419` maps no legacy enrichment variable.
- `apps/refinery/main.py:445-456` resolves all stages but passes only four models.
- `ai_editor.py:348-425` already accepts and uses `enrichment_model` correctly when supplied.
- `ai_editor.py:1823-1858` accepts any JSON-parsable cache and writes caches non-atomically.
- `test_model_registry.py:228-248` claims every stage is explicit but omits enrichment; this currently fails in pinned/no-warn mode.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Model tests | `.venv/bin/python -m pytest tests/unit/infrastructure/llm/test_model_registry.py -q` | all pass |
| Stage 4 tests | `.venv/bin/python -m pytest tests/unit/editorial/test_enrichment_fields.py -q` | all pass |
| Config validation | `make config-validate && make config-docs-check` | exit 0 |
| Lint/type | `.venv/bin/python -m ruff check <changed-python-files> && make type` | exit 0 |

## Scope

**In scope**: the listed model/config/Refinery/editor/test files and generated config-field docs if required.

**Out of scope**: changing model defaults, prompt content, enrichment field semantics, or making Stage 4 mandatory—that is plan 028.

## Git workflow

- Branch: `advisor/027-stage4-routing-cache`
- Commit example: `fix(editorial): wire enrichment model and validate cache`.

## Steps

### Step 1: Add the configuration field everywhere

Add optional `enrichment_model` to `OllamaConfig`, the shared model-name validator, sample `config.toml`, config documentation, and legacy environment mapping (`OLLAMA_ENRICHMENT_MODEL`). Preserve default inheritance from `ollama.model` when absent.

**Verify**: config tests cover TOML, nested env, legacy env, invalid names, explicit override, and inheritance.

### Step 2: Pass the resolved model into Refinery

Pass `resolved_models["enrichment"]` into `EditorAgent`. Do not resolve it a second time with different policy. Update explicit-stage fixtures to name enrichment and assert provenance.

**Verify**: a focused test observes the configured enrichment model in the provider call and pinned/no-warn mode passes.

### Step 3: Validate and atomically replace caches

On cache read, require a JSON object and validate it through `EnrichmentSchema`. On JSON/type/schema failure, log a secret-free warning, regenerate, and replace the cache via a temporary file plus atomic rename. Reuse a validated model dump only.

**Verify**: tests cover scalar, list, missing field, stale enum, corrupt JSON, valid cache, regeneration failure, and no partial file after an interrupted write.

## Test plan

- Strict config tests for TOML, nested/legacy environment overrides, invalid model names, inheritance, and explicit enrichment selection.
- Refinery construction test proving the one resolved model reaches the Stage 4 provider call.
- Cache tests for valid reuse and every malformed/stale/interrupted case named above.
- Focused model/editorial tests plus config docs, lint, and typecheck gates.

## Done criteria

- [ ] Every supported configuration layer can express the enrichment model.
- [ ] Refinery passes the resolved model to `EditorAgent`.
- [ ] Pinned/no-warn explicit-stage tests pass.
- [ ] Invalid caches regenerate and valid caches reuse without an LLM call.
- [ ] Config docs/checks, focused tests, lint, and typecheck pass.

## STOP conditions

- Stop if adding the field changes default model selection for existing configurations.
- Stop if atomic replacement is unsupported on the configured cache filesystem; report filesystem semantics before choosing a fallback.

## Maintenance notes

Adding any future model stage requires the registry, strict schema, env mapping, construction wiring, explicit-stage fixtures, and config docs in one change.
