# Plan 020: Make backend CI enforce the canonical frontend schema

> **Executor instructions**: Follow the steps exactly and update plan 020 in `plans/README.md` when complete.
>
> **Drift check (run first)**: `git diff --stat e43bd30..HEAD -- .github/workflows/ci.yml tests/test_contracts_sync.py README.md AGENTS.md docs/PIPELINE_CONTRACTS.md news_collector/contracts/frontend_schema.py`

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: HIGH
- **Depends on**: none
- **Category**: tests
- **Planned at**: backend `e43bd30`; frontend schema observed at `0cdca74`; 2026-07-21

## Why this matters

Backend CI checks out the correct frontend file but copies it to a path the parity test does not read. The test then skips, even though active documentation says parity is mandatory. Correcting this may expose real drift, so the gate must fail closed and any incompatibility must be resolved explicitly.

## Current state

- Frontend authority is sibling `../noticiencias/src/content.config.ts`.
- `.github/workflows/ci.yml:69-85` checks out `src/content.config.ts` but copies it to `../noticiencias/src/content/config.ts`.
- `tests/test_contracts_sync.py:34-37` resolves the canonical sibling path; `:96-104` skips when it is absent.
- `README.md`, `AGENTS.md`, `docs/PIPELINE_CONTRACTS.md`, and the module header in `news_collector/contracts/frontend_schema.py` still name the wrong path.
- The frontend's own `scripts/check-contract-sync.js` is the executable parity reference; do not create a third schema interpretation.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Focused test | `.venv/bin/python -m pytest tests/test_contracts_sync.py -q` | passes, no skips |
| Backend contract | `.venv/bin/python -m pytest tests/test_contracts_frontend.py tests/test_contracts_sync.py -q` | all pass |
| Frontend parity | `cd ../noticiencias && npm run check:contract-sync` | exit 0 |

## Scope

**In scope**: `.github/workflows/ci.yml`, `tests/test_contracts_sync.py`, the four active backend path references listed above, and a focused test fixture if required.

**Out of scope**: changing either schema's fields merely to make the test green, weakening the one tolerated date-type divergence, or changing frontend content.

## Git workflow

- Branch: `advisor/020-enforce-schema-parity`
- Commit example: `fix(ci): enforce canonical frontend schema parity`.

## Steps

### Step 1: Canonicalize every active path reference

Replace `src/content/config.ts` with `src/content.config.ts` in active backend documentation and module comments. Keep examples repository-relative.

**Verify**: `rg -n 'src/content/config\.ts' README.md AGENTS.md docs news_collector` returns no active matches.

### Step 2: Put the sparse checkout where the test expects it

Copy the checked-out file to `../noticiencias/src/content.config.ts`, creating only the sibling directory required by the test. Do not rename it or fabricate `src/content/`.

**Verify**: reproduce the workflow layout locally and run the focused test; it must pass with `0 skipped`.

### Step 3: Fail closed when CI promised a schema

Parameterize the test or CI environment so an expected sparse checkout missing in CI is a failure, while an explicitly local run without the sibling can retain a documented skip if that developer workflow is intentional. Add a test for both modes.

**Verify**: missing expected schema exits nonzero; present matching schema passes; a deliberately changed required field fails.

## Test plan

- Model path/parity cases after the existing parser tests in `tests/test_contracts_sync.py`.
- Cover correct path, absent expected checkout, matching schemas, and a deliberate field mismatch.
- Run the frontend parity command as a cross-check.

## Done criteria

- [ ] Backend CI places the schema at the canonical path.
- [ ] CI parity runs without skip.
- [ ] Active docs contain no old path.
- [ ] Both backend and frontend parity commands pass.

## STOP conditions

- Stop if the now-active gate exposes schema drift; report the exact field/type mismatch before modifying either authority.
- Stop if fork PR policy cannot access the frontend repository; preserve a fail-closed committed snapshot fallback rather than skipping silently.

## Maintenance notes

Any future frontend schema move must update the sparse checkout, test resolver, contract docs, and snapshot path in the same change.

