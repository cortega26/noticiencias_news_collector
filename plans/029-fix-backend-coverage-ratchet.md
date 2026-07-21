# Plan 029: Point backend coverage gates at production code

> **Executor instructions**: Establish an honest baseline; do not lower thresholds to preserve the misleading selected-package percentage. Update plan 029 after CI-equivalent checks pass.
>
> **Drift check (run first)**: `git diff --stat e43bd30..HEAD -- pyproject.toml scripts/coverage_ratcheter.sh .coverage-baseline .github/workflows/ci.yml tests`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plan 019
- **Category**: tests
- **Planned at**: backend `e43bd30`, 2026-07-21

## Why this matters

The reported backend coverage percentage excludes serving, collectors, editorial components, infrastructure, scoring, and apps. The changed-file ratchet then searches `src/**/*.py`, a tree that does not contain production modules, so its advertised 90% changed-file gate evaluates nothing. Coverage must describe the package that ships and reject untested high-risk changes.

## Current state

- `pyproject.toml:134-138` passes five package-specific `--cov` options.
- `pyproject.toml:155-162` repeats that selected source list.
- `scripts/coverage_ratcheter.sh:153-163` discovers changed modules only under `src/**/*.py`.
- `scripts/coverage_ratcheter.sh:227-259` applies 80% global, 90% changed-line, and 70% changed-branch thresholds to that incomplete/mismatched input.
- `.github/workflows/ci.yml:87-122` generates XML and invokes the ratchet.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Coverage | `.venv/bin/python -m pytest --cov-report=xml:reports/coverage/coverage.xml` | tests pass; XML covers package root |
| Ratchet | `COVERAGE_XML=reports/coverage/coverage.xml bash scripts/coverage_ratcheter.sh check --base-ref HEAD^` | exit 0 on unchanged baseline |
| Ratchet tests | `.venv/bin/python -m pytest tests/test_coverage_ratcheter.py -q` | all pass |

## Scope

**In scope**: pytest/coverage configuration, ratchet script, baseline, CI coverage job, and ratchet self-tests.

**Out of scope**: immediately achieving 80% across every previously excluded module, deleting tests, excluding high-risk packages to improve a number, or changing application behavior.

## Git workflow

- Branch: `advisor/029-honest-backend-coverage`
- Commit example: `fix(ci): ratchet coverage across production package`.

## Steps

### Step 1: Instrument the actual production roots

Set coverage source to the full `news_collector` package and explicitly chosen application entrypoints under `apps/` that contain production logic. Keep only justified generated/boilerplate omissions. Remove redundant per-package `--cov` flags.

**Verify**: XML contains representative files from `serving`, `collectors`, `components`, `infrastructure`, and `scoring`.

### Step 2: Normalize changed paths correctly

Discover `news_collector/**/*.py` plus declared `apps/**/*.py` paths. Normalize Cobertura filenames and Git paths to one repository-relative form; disambiguate same-basename modules by full path.

**Verify**: self-tests cover a changed covered file, changed uncovered file, missing XML entry, same basename in two packages, deletion, rename, and no Python change.

### Step 3: Record an honest staged baseline

Measure full-scope line/branch coverage. Replace the selected-scope 80% baseline with the measured full-scope baseline and a no-regression ratchet. Retain strong changed-file thresholds for newly changed production lines; document a staged target rather than pretending current full coverage is 80%.

**Verify**: baseline check passes at current measured coverage; a synthetic uncovered changed file fails the 90% gate.

### Step 4: Make CI fail clearly

Print total scope, changed modules, missing files, line/branch values, and baseline SHA. Ensure an empty changed-module set is valid only when Git truly reports no relevant Python changes.

**Verify**: CI-equivalent command fails on a deliberately uncovered changed fixture and passes after its test is added.

## Test plan

- Coverage XML assertions for representative modules in every declared production root.
- Ratchet self-tests for covered/uncovered change, missing XML entry, basename collision, rename, deletion, and no relevant change.
- Honest-baseline pass and intentional line/branch regression failures.
- CI-equivalent full coverage generation and ratchet execution from the same base-ref semantics as pull requests.

## Done criteria

- [ ] Coverage XML represents all production package areas.
- [ ] Changed-file discovery uses real paths.
- [ ] Ratchet self-tests cover pass/fail/path edge cases.
- [ ] Baseline is honest and no-regression is enforced.
- [ ] CI-equivalent coverage and full tests pass.

## STOP conditions

- Stop if full-package instrumentation makes tests fail because importing a module performs external I/O; report that import side effect as a separate defect.
- Stop if app coverage cannot be attributed reliably; keep it as a separately reported denominator rather than blending misleading numbers.

## Maintenance notes

New top-level production packages or apps must be added to both instrumentation and changed-path discovery. Baseline updates require an explained coverage increase/decrease, never an automatic overwrite.
