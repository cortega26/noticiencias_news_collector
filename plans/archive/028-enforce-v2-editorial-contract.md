# Plan 028: Enforce complete schema-v2 editorial artifacts

> **Executor instructions**: This is a coordinated backend/frontend contract rollout. Do not enable strict CI until backend fallback semantics and current content are ready. Update plan 028 after both repositories pass strict validation.
>
> **Drift check (run first)**: backend `git diff --stat e43bd30..HEAD -- news_collector/components/editorial/ai_editor.py news_collector/contracts/frontend_schema.py tests`; frontend `git diff --stat 0cdca74..HEAD -- src/content.config.ts scripts/check-editorial-fields.js package.json .github/workflows/content-guard.yml src/content/posts tests`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans 020, 027
- **Category**: bug/tests
- **Planned at**: backend `e43bd30`, frontend `0cdca74`, 2026-07-21

## Why this matters

Backend generation always declares schema version 2 but omits falsey enrichment fields after a Stage 4 failure. Frontend schema/checker enforcement is optional, so all 30 current v2 posts can lack all six required fields while CI remains green. A version marker must describe an artifact contract, not an aspiration.

## Current state

- Backend `ai_editor.py:1235-1286` documents an empty, non-blocking Stage 4 fallback.
- `ai_editor.py:1936-1971` always sets `schema_version: 2` and copies only truthy enrichment values.
- Frontend `src/content.config.ts:102-107` makes v2 refinement conditional on `STRICT_EDITORIAL`.
- `scripts/check-editorial-fields.js:176-224` exits zero with warnings unless that environment variable is exactly `true`.
- `package.json:32-43` and Content Guard run the checker without strict mode.
- Current baseline: 30 v2 posts × six missing fields = 180 warnings. Do not flip the switch before resolving this baseline.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Backend Stage 4 | `.venv/bin/python -m pytest tests/unit/editorial/test_enrichment_fields.py -q` | all pass |
| Frontend strict | `cd ../noticiencias && STRICT_EDITORIAL=true npm run check:editorial-fields` | exit 0 |
| Frontend baseline | `cd ../noticiencias && npm run lint && npm run validate:content` | exit 0, no editorial warnings |
| Cross-repo smoke | `.venv/bin/python scripts/validate_frontend_publication.py --frontend-root ../noticiencias` | exit 0 with a generated v2 fixture |

## Scope

**In scope**: backend Stage 4 failure/state handling and v2 output tests; frontend schema/checker/CI strictness; explicit remediation of current v2 content through generated backfill or intentional version correction.

**Out of scope**: hand-inventing scientific enrichment, silently fabricating sources/confidence, changing field meanings, or weakening minimum field shapes.

## Git workflow

- Matching branches: `advisor/028-enforce-v2-editorial-contract`
- Commit examples: `fix(editorial): quarantine incomplete v2 output`; `fix(content): enforce v2 enrichment fields`.

## Steps

### Step 1: Choose fail-closed generation semantics

Treat a requested v2 article with missing/invalid Stage 4 output as retryable editorial failure: do not write/publish an incomplete v2 file. Persist a stable failure code/state so Refinery can retry or let an editor supply validated fields. Do not silently relabel new content as legacy v1.

**Verify**: backend tests prove complete v2 succeeds and empty/partial/invalid Stage 4 output does not reach the publishing writer.

### Step 2: Produce a real deterministic v2 smoke artifact

Update backend publication smoke to exercise `EditorAgent` assembly with deterministic provider responses and every v2 field, rather than a hand-built schema-v1 fixture. Expand workflow path filters to editorial generator, prompts, model configuration, schema, and writer changes.

**Verify**: changing/removing one required field makes the cross-repo smoke fail.

### Step 3: Resolve existing content intentionally

Generate a report of all incomplete v2 posts. Backfill only from traceable source/editorial data, or explicitly migrate posts that were never truly v2 under a documented compatibility decision. Require human review of factual claims, confidence, and sources.

**Verify**: strict checker reaches zero errors; diff contains no unreviewed fabricated source URLs or claims.

### Step 4: Enable strict enforcement everywhere

Make v2 refinement unconditional in the content schema and make the standalone checker fail whenever errors exist. Remove `STRICT_EDITORIAL` as a bypass, or retain it only for an explicitly named local legacy-report command that CI never uses.

**Verify**: lint, content validation, Content Guard equivalent, build, and cross-repo smoke all fail on a partial v2 fixture and pass on a complete one.

## Test plan

- Backend Stage 4/assembly cases for complete, empty, partial, invalid, cached, and provider-failure v2 output.
- Frontend schema/checker cases for v1 compatibility, complete v2, and each individually missing v2 field.
- Reviewed corpus migration report and zero-error strict validation across all current posts.
- Cross-repo producer-to-frontend smoke using real deterministic v2 assembly, followed by full repository gates.

## Done criteria

- [ ] Backend never publishes an incomplete new v2 artifact.
- [ ] Current v2 corpus passes strict validation with reviewed data.
- [ ] Frontend CI has no non-strict bypass for v2 fields.
- [ ] Publication smoke exercises real v2 assembly.
- [ ] Both repositories' full required gates pass.

## STOP conditions

- Stop if no human-reviewed source exists for backfilling current scientific fields; report the affected posts instead of generating facts.
- Stop if the product owner explicitly requires Stage 4 failure to remain non-blocking; request a schema-version/fallback decision before coding.

## Maintenance notes

Future schema versions need explicit producer, consumer, migration, and CI rollout semantics. A defaulted version must never be used to bypass new-content editorial intent.
