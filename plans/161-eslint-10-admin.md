# Plan 161: Migrate the admin eslint chain to eslint 10 (drop the 5 high advisories)

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat d9a76cb5..HEAD -- apps/admin/package.json apps/admin/package-lock.json apps/admin/eslint.config.mjs .github/workflows/ci.yml docs/ci.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S-M
- **Risk**: MEDIUM (major toolchain bump in the admin app; lint behaviour can shift)
- **Depends on**: plan 145 (merged; left the gate at `--audit-level=critical`)
- **Category**: dependencies / DX
- **Planned at**: commit `d9a76cb5`, 2026-10-19

## Why this matters

Plan 145 added the admin advisory gate but had to run it at
`npm audit --audit-level=critical`: the five **high** advisories are one
dev-lint chain — `braces@3.0.3` (GHSA-vfj7-8cjw-p6xm, no patched release) →
`micromatch` → `fast-glob` → `astro-eslint-parser@1.4.0` →
`eslint-plugin-astro@1.7.0`. The plan's 0-vulnerability path was verified
installable during 145 (**eslint 10 + `eslint-plugin-astro` 3.2.1 +
`astro-eslint-parser` 3.2.0 → `npm audit` reports 0**) but it was not taken
because it needs a one-line import change in `apps/admin/eslint.config.mjs`,
which 145's scope forbade. This plan authorises exactly that change and nothing
else, so the gate can go back to `--audit-level=high`.

Evidence from plan 145's executor (verified in that worktree, then reverted):
the bumped install resolves cleanly and audits 0; `make admin-lint` then failed
on (a) `Cannot find package '@eslint/js'` (eslint 10 no longer depends on it)
and (b) `SyntaxError: The requested module 'astro-eslint-parser' does not
provide an export named 'default'` at `eslint.config.mjs:7`. Both are
mechanical, not semantic.

## Current state

- `apps/admin/package.json` — devDependencies include `eslint ^9.39.2`,
  `eslint-plugin-astro ^1.5.0`, `@eslint/js` (check the exact range; if absent,
  it is a transitive of eslint 9 and must become a direct devDependency),
  `eslint-plugin-jsx-a11y` (check its version and whether the config uses it —
  its peer range stops at eslint 9 in the version 145 tried).
- `apps/admin/eslint.config.mjs` — line ~7 has a **default** import of
  `astro-eslint-parser`; the 3.x parser exports named symbols
  (`parseForESLint`, …) only.
- `.github/workflows/ci.yml` — `admin-contracts` job, step
  `Admin dependency advisories` runs `npm audit --audit-level=critical` with a
  dated 2026-10-19 comment naming GHSA-vfj7-8cjw-p6xm and the exit path.
- `docs/ci.md` — "Admin contracts" section documents the critical threshold and
  the residual chain.
- `apps/admin/package-lock.json` — braces 3.0.3, astro-eslint-parser 1.4.0,
  eslint-plugin-astro 1.7.0.

## Commands you will need

| Purpose            | Command                                                        | Provenance | Expected on success |
|--------------------|----------------------------------------------------------------|------------|---------------------|
| Install admin      | `make admin-install`                                           | declared   | exit 0              |
| Admin lint/test    | `make admin-lint` / `make admin-test` / `make admin-build`     | declared   | exit 0              |
| Audit (target)     | `cd apps/admin && npm audit --audit-level=high`                | declared   | exit 0, 0 vulns     |
| Lint / types       | `make lint` / `make type`                                      | declared   | exit 0              |
| Unit suite         | `make test`                                                    | declared   | all pass            |
| Docs / inventory   | `make docs-check` / `make inventory-check`                     | declared   | exit 0              |
| Ledger             | `make plans-ledger-check`                                      | declared   | OK                  |

Provenance: all `declared`.

## Scope

**In scope**:

- `apps/admin/package.json` + `apps/admin/package-lock.json` (via npm, not hand-edited)
- `apps/admin/eslint.config.mjs` — **only** the parser import (and any import
  path that eslint 10 moved, e.g. `@eslint/js`), no rule changes
- `.github/workflows/ci.yml` — the admin advisory step threshold/comment
- `docs/ci.md` — the Admin contracts advisory bullet

**Out of scope** (do NOT touch):

- eslint rules or their severities; app code; Astro config; any other workflow
  job; `requirements*.lock`.
- Upgrading Astro itself or unrelated packages. Keep the lock diff scoped to the
  lint chain (npm may re-resolve shared transitive peers; report every non-lint
  change).

## Git workflow

- Branch: `advisor/161-eslint-10`
- Conventional commit, e.g.
  `chore(admin): migrate the eslint chain to v10 and restore the high audit gate (plan 161)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Baseline

1. `make bootstrap`, `make admin-install`, `make admin-lint`, `make admin-test`,
   `make admin-build`, `cd apps/admin && npm audit --audit-level=high` (expect
   exit 1, 5 high). Record the exact counts.

**Verify**: baseline green except the expected audit failure.

### Step 1: Bump the chain

2. Read `apps/admin/eslint.config.mjs` fully and note every import from
   `eslint`, `@eslint/js`, `typescript-eslint`, `astro-eslint-parser`,
   `eslint-plugin-astro`, `eslint-plugin-jsx-a11y`.
3. Install the verified combination with npm (not a hand-edited lock):
   `npm install --save-dev eslint@^10.13.0 eslint-plugin-astro@^3.2.1 astro-eslint-parser@^3.2.0 @typescript-eslint/eslint-plugin@^8.72.0 @typescript-eslint/parser@^8.72.0 @eslint/js@^10.0.1`.
   - If `eslint-plugin-jsx-a11y` is used by the config, find a version compatible
     with eslint 10; if none exists, STOP and report (do not drop the plugin).
   - If npm reports peer conflicts, capture the full output and STOP.

**Verify**: install exits 0; `npm ls eslint eslint-plugin-astro astro-eslint-parser @eslint/js --depth=0` shows the new majors.

### Step 2: Fix the mechanical imports

4. Change the astro parser import to the named form, e.g.
   `import { parseForESLint as astroParser } from "astro-eslint-parser";`
   (keep the local identifier the rest of the config already uses).
5. Add/adjust the `@eslint/js` import if eslint 10 moved it.
6. Run `make admin-lint`.
   - If new **mechanical** findings appear (formatting/import order), run the
     repo's lint-fix target and report the count.
   - If findings are **semantic** (new rule behaviour), STOP and report the
     rule ids and files; do not disable rules.

**Verify**: `make admin-lint` exits 0.

### Step 3: Restore the gate and update the docs

7. Change the CI step to `npm audit --audit-level=high`, replace the dated
   critical-threshold comment with a short note that the eslint 10 chain
   resolves the braces chain and that the gate is high again (keep the GHSA id
   for history).
8. Update `docs/ci.md`'s Admin contracts bullet: high threshold, the migration,
   and that the npm Dependabot entry remains the early-warning path.

**Verify**: `cd apps/admin && npm audit --audit-level=high` → exit 0, 0
vulnerabilities; `grep -n "audit-level" .github/workflows/ci.yml docs/ci.md`.

### Step 4: Gates

9. `make admin-test`, `make admin-build`, `make lint`, `make type` (post-commit),
   `make test`, `make test-boundaries`, `make docs-check`,
   `make inventory-refresh && make inventory-check`, `make plans-ledger-check`.
10. Report the lock diff by package groups: lint chain vs anything else.

**Verify**: all exit 0; `git diff --name-only main...HEAD` lists exactly the
four in-scope files.

## Test plan

- The admin lint/test/build targets are the behavioural evidence.
- The audit at `high` exiting 0 is the security evidence; record the counts
  before/after.
- No new unit tests are required; if the config change alters which files are
  linted, say so.

**Verify**: `make test` green (backend suite unaffected).

## Done criteria

All must hold:

- [ ] `cd apps/admin && npm audit --audit-level=high` → exit 0, 0 vulnerabilities
- [ ] `make admin-lint`, `make admin-test`, `make admin-build` → exit 0
- [ ] CI step and `docs/ci.md` say `high`, with the migration note
- [ ] No eslint rule disabled; no app code changed
- [ ] `make lint`, `make type`, `make test`, `make test-boundaries`, `make docs-check`, `make inventory-check`, `make plans-ledger-check` → exit 0
- [ ] `git diff --name-only main...HEAD` lists only the four in-scope files
- [ ] `plans/README.md` row 161 updated by the reviewer

## STOP conditions

- Any need to disable/loosen an eslint rule, or semantic findings you cannot fix
  mechanically → report rule ids and files.
- `eslint-plugin-jsx-a11y` has no eslint-10-compatible release and the config
  uses it → report; do not remove the plugin.
- The bump forces an Astro upgrade or touches app code → STOP.
- `npm audit` still reports high advisories after the bump → report the chain;
  do not lower the gate again without a dated decision.

## Maintenance notes

- The admin eslint chain is now a **major-version surface**: pin majors in
  `package.json` and let the monthly npm Dependabot entry propose bumps; never
  hand-edit `package-lock.json`.
- If a future parser drops another export, fix the import mechanically — do not
  downgrade the gate.
