# Plan 024: Make pyproject the canonical dependency and image source

> **Executor instructions**: Follow each verification gate. Update plan 024 in `plans/README.md` when complete.
>
> **Drift check (run first)**: `git diff --stat e43bd30..HEAD -- pyproject.toml requirements.txt requirements.lock requirements-refinery.lock requirements-security.lock scripts/sync_lockfiles.py Dockerfile .github/workflows/manual-lock-sync.yml docs/adr/0002-hash-pinned-lockfiles.md`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plan 019
- **Category**: migration/dx
- **Planned at**: backend `e43bd30`, 2026-07-21

## Why this matters

Runtime locks are compiled from `requirements.txt`, while Refinery/security locks come from `pyproject.toml`; those manifests disagree about Click, Playwright, Scrapling, GitPython, and version ranges. The production image then installs both runtime and test/security lockfiles, so security tools can replace runtime-resolved packages. One manifest and explicit capability extras are required before dependency upgrades are trustworthy.

## Current state

- `requirements.txt:1-29` lists direct runtime dependencies, including Click, Playwright, and Scrapling.
- `pyproject.toml:9-38` defines the wheel's base dependencies but omits those three; `:40-60` defines Refinery/security/test extras.
- `scripts/sync_lockfiles.py:14-68` compiles the main lock from `requirements.txt` and the other locks from `pyproject.toml`.
- `Dockerfile:11-18` installs `requirements.lock` and `requirements-security.lock` into one production environment, then installs Chromium.
- `.github/workflows/manual-lock-sync.yml:41-56` ignores `requirements-refinery.lock` when deciding whether to commit.
- ADR 0002 requires hash-locked, reproducible environments; preserve that rule.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Lock sync | `.venv/bin/python scripts/sync_lockfiles.py --check` | exit 0, no diff |
| Package graph | `.venv/bin/python -m pip install --dry-run '.' '.[refinery]'` | both resolve |
| Image | `docker build -t noticiencias-collector:plan024 .` | exit 0 |
| Image audit | `docker run --rm noticiencias-collector:plan024 python -m pip check` | exit 0 |
| Tests | `.venv/bin/python -m pytest -q` | all pass |

## Scope

**In scope**: the manifests/locks/generator/Dockerfile/manual workflow above, packaging tests, and ADR updates.

**Out of scope**: upgrading vulnerable versions (plan 025), changing scraper behavior, adding new collector strategies, or shipping security tools in the final runtime image.

## Git workflow

- Branch: `advisor/024-canonical-backend-dependencies`
- Commit example: `refactor(deps): derive environments from pyproject`.

## Steps

### Step 1: Characterize capability boundaries

Map imports and executable paths for Click, Playwright, Scrapling, GitPython, Streamlit, and security/test tools. Decide which are required by the minimal collector, headless enrichment, serving API, and Refinery. Record this classification in `pyproject.toml` extras and the ADR.

**Verify**: focused import smoke tests prove each declared environment has its promised entrypoints and does not require undeclared optional packages.

### Step 2: Make `pyproject.toml` authoritative

Move every direct dependency and range into the base or a named extra. Remove `requirements.txt` as an independent hand-maintained authority (delete it or generate it with a prominent generated header). Update `LOCK_TARGETS` so every hash lock compiles from `pyproject.toml` and explicit extras.

**Verify**: `rg -n 'requirements\.txt' scripts Makefile .github Dockerfile docs` finds only intentional generated/transition references; lock sync is idempotent.

### Step 3: Isolate production from tooling

Build the final collector image from only its runtime/headless lock set. Run Bandit, pip-audit, Semgrep, and pytest in CI or a disposable build/test stage, not the final image. Verify installed versions in the final image match the runtime lock and `pip check` is clean.

**Verify**: image package inventory contains no pytest/Bandit/pip-audit/Semgrep unless explicitly runtime-required; locked runtime packages match.

### Step 4: Commit every generated lock together

Update manual lock sync to check and stage all `LOCK_TARGETS`, including Refinery. Add a test that extracts generator outputs and proves the workflow's clean/stage list is identical.

**Verify**: changing only `requirements-refinery.lock` is detected and staged by the workflow logic.

## Test plan

- Clean lock compilation twice with byte-identical output and no uncommitted diff.
- Fresh base, Refinery, security, and test environment installs from their exact locks.
- Wheel/sdist metadata and import/entrypoint checks for every declared capability.
- Production image smoke proving runtime packages are present and test/security-only packages do not perturb resolution.

## Done criteria

- [ ] One canonical direct-dependency manifest exists.
- [ ] Every lock derives from explicit `pyproject.toml` extras.
- [ ] Final production image contains only runtime capabilities.
- [ ] All three locks participate in manual refresh.
- [ ] Package, image, lock-sync, and full test gates pass.

## STOP conditions

- Stop if current production relies on an undeclared package not captured by import/entrypoint tests.
- Stop if separating security tools changes runtime package versions; report the conflicting packages before forcing a constraint.
- Stop if lock generation requires advisory upgrades; keep this structural plan separate from plan 025.

## Maintenance notes

Future capabilities must be assigned to a base/extra before lock generation. Reviewers should reject direct edits to generated locks without an accompanying manifest/generator change.
