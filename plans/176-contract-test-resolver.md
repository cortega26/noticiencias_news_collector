# Plan 176: Follow the extracted frontend schema in the backend contract test (hotfix)

> **P1 hotfix**: backend `main` CI is red since frontend `ee12c38d`/`7ff45dae`
> moved the Zod schema to `src/schemas/post.ts`. Fix the test and the CI
> sparse checkouts; no product code.
>
> **Drift check**: `git diff --stat 0b751752..HEAD -- tests/test_contracts_sync.py .github/workflows/ci.yml`

## Status

- **Priority**: P1 (red main)
- **Effort**: S-M
- **Risk**: MEDIUM (the contract gate must stay strict)
- **Depends on**: 174 (frontend schema extraction)
- **Category**: CI / cross-repo contract
- **Planned at**: backend `0b751752`, 2026-10-20

## Why this matters

`tests/test_contracts_sync.py::test_frontend_schema_field_parity` extracts
top-level fields from `../noticiencias/src/content.config.ts` with a regex
pinned to six-space indentation. Frontend plan 174 (merged `ee12c38d`) moved
the structural object to `src/schemas/post.ts` (two-space indentation), and
`content.config.ts` now imports it. The extractor finds **0** fields and the
test fails; backend CI is red on `06e291ad` and `0b751752`.

The frontend's Node checker already follows the import (plan 174). The backend
must do the same, and its CI sparse checkouts must include the module.

## Current state

- `tests/test_contracts_sync.py:39` — `_FRONTEND_CONFIG = ../noticiencias/src/content.config.ts`.
- `:44-58` — `_ZOD_FIELD_RE = ^\s{6}(\w+)\s*:\s*z...`; `_extract_zod_fields` returns the set.
- `.github/workflows/ci.yml` — unit/type job sparse-checks out
  `src/content.config.ts` then copies it to `../noticiencias/src/` (lines
  ~46-57); `contract-parity` sparse-checks out the Node checker +
  `src/content.config.ts` (lines ~99-108).
- Frontend: `content.config.ts` has `import { postStructuralSchema } from
  './schemas/post';` and `schema: postStructuralSchema.superRefine(...)`;
  `src/schemas/post.ts` has `export const postStructuralSchema = z.object({...})`
  with 41 fields, 2-space indent, module-scope comments.

## Scope

**In scope**: `tests/test_contracts_sync.py`, `.github/workflows/ci.yml`.
**Out of scope**: the frontend repo, product code, the parity test (plan 175B),
`jsonschema` (a separate decision).

## Steps

1. **Resolver**: add `_resolve_schema_source(config_path) -> (source, path)`:
   - read the config;
   - if it contains `schema: z.object(` (inline), parse the config;
   - if it contains `schema: <identifier>`, find the import
     (`import { <identifier> } from '<relative>'`, including default/named and
     `~/` aliases), resolve within the frontend repo, read the module, and
     locate `(export )?const <identifier> = z.object(`;
   - if no schema/import is found, raise a descriptive `ValueError`.
2. **Parser**: replace the indentation-pinned regex with a depth-aware
   extractor for the `z.object({...})` body:
   - track braces/brackets/parens, single/double/backtick strings with escapes,
     and `//` / `/* */` comments;
   - at depth 1 of the object, capture identifier keys followed by `:`;
   - return the set; assert it is non-empty (41 expected).
   Keep an inline-schema path for fixtures/tests.
3. **Tests**: add focused unit tests for:
   - the inline 6-space layout;
   - the module 2-space layout (a temp fixture mirroring `post.ts`);
   - an unresolvable import raises.
   Keep `test_frontend_schema_field_parity` strict (set equality with
   `AstroPost.model_fields`).
4. **CI**:
   - unit/type job: add `src/schemas/post.ts` to the sparse checkout and copy
     it to `../noticiencias/src/schemas/post.ts` (mkdir);
   - `contract-parity` job: add `src/schemas/post.ts` to its sparse checkout
     (the Node checker follows the import);
   - keep `CI_EXPECTED_FRONTEND_SCHEMA: "1"` (fail closed on a missing file).
5. **Verify**:
   - `make test` (the contract test passes with the sibling frontend);
   - simulate CI: a temp `../noticiencias` containing only `content.config.ts`
     + `schemas/post.ts`, run the contract test (and the Node checker if
     cheap) → green; remove the temp;
   - `make lint`, `make type` (committed), `make test-contracts`,
     `make test-boundaries`, `make docs-check`,
     `make inventory-refresh && make inventory-check`, `make plans-ledger-check`.

## Done criteria

- [ ] The backend contract test resolves inline and module schemas; 41 fields
- [ ] CI unit/type + contract-parity checkouts include `src/schemas/post.ts`
- [ ] Simulated CI (only config + module) passes; missing module fails closed
- [ ] Backend CI on the merge commit is green
- [ ] Ledger row 176 updated by the reviewer

## STOP conditions

- The module cannot be resolved without executing TypeScript (report).
- A field-set mismatch that is not explained by the extraction (report; do not
  weaken the test).
- Any frontend change is needed (it is not).
