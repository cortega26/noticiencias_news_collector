# Plan 030: Make developer and CI toolchains reproducible

> **Executor instructions**: Follow each verification gate. Change only dependency/tooling configuration; do not combine product changes with this plan. Update plan 030 in `plans/README.md` when complete.
>
> **Drift check (run first)**:
> `git diff --stat e43bd30..HEAD -- pyproject.toml requirements*.txt Makefile .github/actions/setup-python-env .github/workflows scripts`
> `git -C ../noticiencias diff --stat 0cdca74..HEAD -- package.json package-lock.json .nvmrc workers/package.json workers/package-lock.json`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/019-remove-tracked-virtualenv.md, plans/024-canonicalize-backend-dependencies.md
- **Category**: dx
- **Planned at**: backend `e43bd30`, frontend `0cdca74`, 2026-07-21

## Why this matters

Runtime dependencies are locked, but several test, lint, audit, and release tools are installed from floating ranges or ad hoc workflow commands. The frontend also permits incompatible versions of the Vitest core/plugin pair and Node type definitions outside its Node 24 runtime. A clean checkout must use the same tool versions locally and in every CI job.

## Current state

- `pyproject.toml` declares broad development-tool ranges while `requirements-security.lock` covers only a narrow audit environment.
- `Makefile` installs developer tools separately from the hashed runtime lock.
- `.github/actions/setup-python-env/action.yml` is the shared Python setup action, but specialized workflows still perform their own installs.
- `../noticiencias/package.json:13-15` requires Node 24, while `@types/node` is on major 25; `vitest` is ranged and `@vitest/coverage-v8` is exact, so the installed versions can diverge.
- `../noticiencias/.nvmrc` is the local Node version source; preserve it as the runtime authority.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Backend install | `make bootstrap-dev` | one documented command creates `.venv` from hash-checked locks |
| Backend checks | `make lint && make typecheck && make test` | exit 0 |
| Frontend graph | `npm --prefix ../noticiencias ci && npm --prefix ../noticiencias ls vitest @vitest/coverage-v8 @types/node` | exit 0; Vitest pair is the same release and Node types are major 24 |
| Frontend checks | `npm --prefix ../noticiencias run lint && npm --prefix ../noticiencias run test:audit` | exit 0 |

## Scope

**In scope**: backend developer/test lock input and generated lock, `Makefile`, shared setup action and workflows that install Python tools, frontend root and Worker manifests/lockfiles, `.nvmrc`, and dependency-consistency checks.

**Out of scope**: runtime dependency consolidation (plan 024), vulnerability-driven upgrades (plans 025 and 032), test coverage policy (plans 029 and 031), or application behavior.

## Git workflow

- Branch: `advisor/030-reproducible-toolchains` in each affected repository.
- Commit example: `build: lock developer toolchains`.
- Keep backend and frontend commits independently revertible; do not push without operator instruction.

## Steps

### Step 1: Create a hash-locked backend developer environment

Add an explicit development/test dependency input and a generated hash-locked output using the same locking mechanism established by plan 024. Include pytest and plugins, coverage, Ruff, mypy, Bandit, pip-audit, pip-tools, pre-commit, and release/check scripts actually invoked by repository commands. Change `make bootstrap-dev` to install runtime plus developer locks without unconstrained follow-up installs.

**Verify**: delete a disposable `.venv`, run `make bootstrap-dev`, then `make lint && make typecheck` → all commands exit 0 without downloading an undeclared tool.

### Step 2: Route Python workflows through the same setup contract

Update `.github/actions/setup-python-env/action.yml` to accept a runtime-only or developer-tooling mode and include all selected lockfiles in its cache key. Replace workflow-local tool installs with that action. Add a lock freshness check that regenerates to a temporary file and diffs it.

**Verify**: `rg -n "pip install (pytest|ruff|mypy|bandit|pip-audit|pip-tools)" .github` → no workflow-local floating installs; the lock freshness command exits 0.

### Step 3: Align the Node runtime and test packages

In both frontend manifests, pin packages that must move in lockstep. Keep root `vitest` and `@vitest/coverage-v8` on exactly the same version, align `@types/node` with Node 24, and make the Worker use the same test runner release unless a documented Cloudflare compatibility constraint requires a separately exact version. Preserve Node 24 in `engines` and `.nvmrc`.

**Verify**: `npm --prefix ../noticiencias ci && npm --prefix ../noticiencias ls vitest @vitest/coverage-v8 @types/node` → no invalid, extraneous, or mismatched nodes.

### Step 4: Add toolchain assertions to CI

Add early checks for Python lock freshness, Node/npm versions, manifest/lock synchronization, and the Vitest/plugin equality invariant. Make errors name the expected and observed version.

**Verify**: CI-equivalent commands pass; deliberately changing a copied lock or fixture version makes its assertion fail nonzero.

## Test plan

- Test backend bootstrap from an empty disposable environment and rerun it to confirm idempotency.
- Test runtime-only and developer modes of the setup action with an action-lint/static validation available in the repo.
- Test root and Worker clean installs, `npm ls`, existing lint, type, and unit commands.

## Done criteria

- [ ] Every CI-invoked Python tool has one exact lock source.
- [ ] No specialized workflow performs a floating install of covered tools.
- [ ] Frontend Vitest core/coverage versions match exactly and Node types match Node 24.
- [ ] Clean backend and frontend installs reproduce checks.
- [ ] Only dependency/tooling files and plan status changed.

## STOP conditions

- Stop if plan 024 has not established one canonical runtime lock source.
- Stop if a tool cannot be hash-locked from supported artifacts; document the exact package/platform instead of disabling hashes globally.
- Stop if Cloudflare requires an incompatible Vitest major; isolate and document it rather than forcing a broken shared version.

## Maintenance notes

Renovation updates must change tool inputs and generated locks together. Reviewers should reject workflow-local installs that bypass the shared action.
