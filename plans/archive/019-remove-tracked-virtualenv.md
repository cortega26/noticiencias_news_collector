# Plan 019: Rebuild the backend environment exclusively from lockfiles

> **Executor instructions**: Run each step and verification in order. Update plan 019 in `plans/README.md` when done.
>
> **Drift check (run first)**: `git diff --stat e43bd30..HEAD -- .venv .gitignore Makefile .github/actions/setup-python-env/action.yml .pre-commit-config.yaml`

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: backend `e43bd30`, 2026-07-21

## Why this matters

The repository tracks 71 virtualenv files, including machine-specific launchers whose shebangs point to an obsolete checkout. The tracked `.bootstrap-complete` stamp causes `make bootstrap` to trust that environment, so documented lint, type, test, and pre-commit commands fail before doing work. A clean clone must contain no environment and must reproduce one from the hash locks.

## Current state

- `.venv/bin/pytest:1` hardcodes `/home/carlos/VS_Code_Projects/noticiencias/.../.venv/bin/python3`.
- `.venv/pyvenv.cfg:1-5` records machine-specific interpreter and creation paths.
- `.gitignore:88-93` ignores `env/` but not `.venv/` or `.venv-refinery/`.
- `Makefile:62-74` trusts a stamp and tests only whether the copied Python binary can execute; it does not detect broken console-script shebangs.
- `.github/actions/setup-python-env/action.yml:22-31` caches `.venv` and then calls `make bootstrap`.
- `.pre-commit-config.yaml:34-39` invokes `.venv/bin/mypy` directly.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Inventory | `git ls-files '.venv/**'` | no output after step 1 |
| Bootstrap | `make bootstrap` | exit 0; environment ready |
| Smoke | `.venv/bin/python -m pytest --version && .venv/bin/python -m mypy --version && .venv/bin/ruff --version` | all exit 0 |
| Baseline | `make lint && make type` | commands execute; any source failures must be reported separately |

## Scope

**In scope**: tracked `.venv/**` removal, `.gitignore`, `Makefile`, `.github/actions/setup-python-env/action.yml`, `.pre-commit-config.yaml`, and bootstrap-focused tests/documentation.

**Out of scope**: upgrading dependencies, fixing current Ruff/Black/Mypy findings, changing Python 3.13 support, or deleting a developer's untracked environment outside the explicit rebuild verification.

## Git workflow

- Branch: `advisor/019-reproducible-venv`
- Commit example: `fix(dx): stop tracking backend virtualenv`.

## Steps

### Step 1: Remove environments from version control

Add `.venv/` and `.venv-refinery/` to `.gitignore`, then remove all currently tracked `.venv/**` paths from the Git index. Do not add replacement binaries, launchers, stamps, or `pyvenv.cfg` files.

**Verify**: `git ls-files '.venv/**' '.venv-refinery/**'` prints nothing; `git check-ignore .venv/bin/python .venv-refinery/bin/python` identifies the new ignore rules.

### Step 2: Make bootstrap validate the environment, not just a stamp

Retain idempotent caching, but validate the expected Python major/minor and representative installed modules/entrypoints before declaring the environment ready. If invalid, remove and recreate the generated environment. Prefer `$(PYTHON_BIN) -m <tool>` for Python tools where practical so execution does not depend on console-script shebang portability.

**Verify**: bootstrap succeeds from no `.venv`; corrupting a disposable console script or Python-version marker causes bootstrap to rebuild or repair it.

### Step 3: Align CI and pre-commit

Keep the CI cache keyed by Python version and all lock inputs. Make the mypy hook use the bootstrapped interpreter/module form. Add a clean-clone bootstrap smoke test or CI assertion that checkout contains no tracked `.venv` files.

**Verify**: `pre-commit run mypy --all-files` reaches Mypy; a cache-miss CI-equivalent bootstrap succeeds.

## Test plan

- Add a shell or Python test for valid, missing, and stale bootstrap environments using temporary directories.
- Assert no tracked file begins with `.venv/`.
- Run the actual lint/type commands to distinguish environment repair from pre-existing source violations.

## Done criteria

- [ ] No virtualenv file is tracked.
- [ ] Fresh bootstrap and cached bootstrap both succeed.
- [ ] Representative tools run through the supported interpreter.
- [ ] CI cache keys include Python and lockfile identity.
- [ ] Only in-scope files and `plans/README.md` changed.

## STOP conditions

- Stop if any tracked `.venv` file is an intentional non-generated fixture; report it and move it to a text fixture separately.
- Stop if clean bootstrap requires changing dependency versions; that belongs to plans 024/025.

## Maintenance notes

Never cache generated environments through Git. When Python or lock inputs change, cache identity and bootstrap validation must change together.
