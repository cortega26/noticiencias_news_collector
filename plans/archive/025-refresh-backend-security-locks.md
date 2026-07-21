# Plan 025: Refresh backend locks and make advisory exceptions exact

> **Executor instructions**: Execute only after plan 024 establishes canonical environments. Update plan 025 in the index when every environment is audited and tested.
>
> **Drift check (run first)**: `git diff --stat e43bd30..HEAD -- pyproject.toml requirements.lock requirements-refinery.lock requirements-security.lock scripts/security_gate.py tests/test_security_gate.py scripts/sync_lockfiles.py`

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: plans 019, 024
- **Category**: security/migration
- **Planned at**: backend `e43bd30`, 2026-07-21

## Why this matters

Current audits report 26 advisories in the runtime lock, 35 in the security/test lock, and 59 in the Refinery lock. Most runtime advisories have fixed versions; FastAPI/Starlette and NLTK require coordinated behavioral validation. Two exceptions expired on 2026-06-30, and the gate compares only a primary ID even when pip-audit reports the allowlisted GHSA as an alias.

## Current state

- `requirements.lock` pins advisory-affected Starlette 0.50.0, NLTK 3.9.2, Pygments 2.19.2, python-dotenv 1.2.1, Requests 2.32.5, and others.
- `scripts/security_gate.py:31-82` contains dated exceptions; `:85-110` intentionally fails on expiry.
- `scripts/security_gate.py:203-213` compares only `vuln["id"]`, not its aliases.
- `tests/test_security_gate.py` is the required pattern for fail-closed report, allowlist, and expiry behavior.
- Lock regeneration belongs to `scripts/sync_lockfiles.py`; do not hand-edit hashes.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Gate tests | `.venv/bin/python -m pytest tests/test_security_gate.py -q` | all pass |
| Lock sync | `.venv/bin/python scripts/sync_lockfiles.py --check` | exit 0 |
| Runtime audit | `.venv/bin/pip-audit -r requirements.lock` | no unapproved fixable advisory |
| Other audits | `.venv/bin/pip-audit -r requirements-refinery.lock && .venv/bin/pip-audit -r requirements-security.lock` | no unapproved fixable advisory |
| Full tests | `.venv/bin/python -m pytest -q` | all pass |

## Scope

**In scope**: dependency minimums, all three generated locks, security gate matching/allowlist, tests, and a compatibility note.

**Out of scope**: suppressing advisories merely to get green CI, changing application features, replacing FastAPI/Streamlit, or retaining packages proven unused.

## Git workflow

- Branch: `advisor/025-refresh-backend-locks`
- Split commits by compatibility cohort, e.g. `fix(deps): upgrade fastapi and starlette`.

## Steps

### Step 1: Capture and classify the advisory baseline

Save machine-readable audit output outside Git or under ignored reports. For every advisory, record package, installed version, fixed versions, environment, reachable feature, and whether a fix exists. Remove unused dependencies instead of upgrading them.

**Verify**: counts reconcile with all three audit outputs; every exception has an owner/reason/expiry and package/environment scope.

### Step 2: Upgrade compatible packages first

Raise direct minimums for fixable compatible releases (including lxml, Mako, Pygments, python-dotenv, Requests, urllib3 and equivalents actually present), regenerate all locks, and run focused subsystem tests after each cohort.

**Verify**: audits no longer report those advisories and lock sync remains deterministic.

### Step 3: Upgrade coupled framework/content stacks

Upgrade FastAPI and Starlette together to a compatible fixed line. Upgrade NLTK and verify tokenization/corpora/scoring behavior with deterministic fixtures. Upgrade Streamlit/Tornado/Scrapling/browser dependencies in the Refinery environment and run authenticated upload/UI smoke tests.

**Verify**: serving API, webhook, scoring/NLP, collectors, and Refinery suites pass; `pip check` passes in each environment.

### Step 4: Normalize advisory identity safely

For each finding, compare the set containing primary `id` plus `aliases` against allowlisted identifiers, additionally scoped to the expected package/environment. Never treat a matching alias alone as sufficient for a different package. Remove expired/fixed exceptions rather than extending dates.

**Verify**: tests cover primary-ID match, alias match, wrong-package alias, expiry, malformed entry, and no-fix exception.

## Test plan

- Lock refresh/drift test from the canonical manifests established by plan 024.
- Advisory-gate fixtures for exact active exception, expired exception, unrelated advisory, invalid JSON, and empty output.
- `pip-audit`/Bandit/gitleaks report validation and production-image dependency scan.
- Focused application smoke plus full backend verification on the refreshed environment.

## Done criteria

- [ ] No fixable advisory remains silently accepted.
- [ ] All exceptions are unexpired, scoped, reasoned, and alias-tested.
- [ ] All locks regenerate from canonical inputs with hashes.
- [ ] `pip check`, focused compatibility tests, and full tests pass in each environment.

## STOP conditions

- Stop if a fixed Starlette line is incompatible with every supported FastAPI version; report the compatibility matrix.
- Stop if an NLTK upgrade changes editorial/scoring output beyond characterized tolerances.
- Stop if an advisory has no fix and reachable impact is unclear; write a scoped risk decision instead of deleting the gate.

## Maintenance notes

Audit exception review is date-sensitive. Dependency automation must update canonical manifests and all derived locks together, with CI retaining fail-closed report validation from plan 011.
