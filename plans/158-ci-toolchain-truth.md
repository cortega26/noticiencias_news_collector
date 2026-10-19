# Plan 158: CI must enforce the toolchain/parity gates, and its venv cache must respect the pins

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 7570c3e4..HEAD -- .github/actions/setup-python-env/action.yml .github/workflows/ docs/ci.md Makefile`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plan 144 (DONE, merged `df690ffe` — it introduced the pins and the two checks)
- **Category**: dx / deps (CI truth)
- **Planned at**: commit `7570c3e4`, 2026-10-19

## Why this matters

Plan 144 pinned the gate tools to the pre-commit revisions and added
`make toolchain-check` / `make lock-parity-check` to `make verify-ci`. Two gaps
remain, and both make the fix *local-only*:

1. **The CI venv cache ignores the pins.** Every workflow passes
   `cache-key: ${{ hashFiles('requirements.lock', 'requirements-security.lock') }}`
   and the shared setup action caches `.venv` including the
   `.bootstrap-complete` stamp. A cache hit therefore **skips** the pinned
   install, so CI keeps whatever tool versions the cache was built with — the
   exact drift plan 144 just removed, resurrected by caching. (The executor of
   144 measured fresh installs resolving ruff 0.17.1 / black 26.10.1 on
   different days; that is the class of variance the pins exist to stop.)
2. **No workflow invokes `make verify-ci`.** CI runs individual targets; the two
   new checks are in no job, so they are enforced only on a developer's machine.

Without this plan, a red `toolchain-check` or a venv/lock divergence is invisible
to every PR.

## Current state

- `.github/actions/setup-python-env/action.yml` — the shared setup: it restores
  the `.venv` cache keyed by the caller's `cache-key` input and skips the
  install when the stamp exists. Read it before editing; the cache path and the
  stamp check are the two moving parts.
- Every workflow that uses the action passes the same literal
  `cache-key: ${{ hashFiles('requirements.lock', 'requirements-security.lock') }}`
  (grep for `cache-key:` in `.github/workflows/`).
- `Makefile:272` — `verify-ci` now includes `toolchain-check lock-parity-check`
  (plan 144). No workflow calls `verify-ci`.
- `ci.yml` jobs: `lint` runs `make lint`; `config` runs `make config-validate`
  and `make config-docs-check`; both already bootstrap the venv.

## Commands you will need

| Purpose          | Command                                                       | Provenance | Expected on success            |
|------------------|---------------------------------------------------------------|------------|--------------------------------|
| Install/baseline | `make bootstrap`                                              | declared   | exit 0                         |
| New checks       | `make toolchain-check && make lock-parity-check`              | declared   | exit 0                         |
| Lint             | `make lint`                                                   | declared   | exit 0                         |
| YAML parse       | `python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]"` | declared | exit 0 |
| Ledger           | `make plans-ledger-check`                                     | declared   | `validate_plans_ledger: OK`    |

Provenance: all `declared`.

## Scope

**In scope**:

- Every `cache-key:` literal in `.github/workflows/*.yml` and the default in
  `.github/actions/setup-python-env/action.yml` (add the pin sources)
- `ci.yml` — a step running the two checks (prefer the existing `lint` job)
- `docs/ci.md` — the cache-key contract and the two CI-enforced checks
- `Makefile` — only if a composite target is cleaner (`make ci-truth`), optional

**Out of scope** (do NOT touch):

- Replacing the per-target CI jobs with a single `make verify-ci` job (bigger
  redesign; not needed to close the gap).
- The pinned versions themselves or `scripts/check_*.py` (plan 144 owns them).
- Production code, tests, or the security-toolchain split (plan 156).

## Git workflow

- Branch: `advisor/158-ci-toolchain-truth`
- Conventional commits, e.g. `ci(dx): run the toolchain/parity gates and key the venv cache on the pins (plan 158)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

`make bootstrap`, `make toolchain-check`, `make lock-parity-check`, `make lint`.
Red baseline → STOP and report.

**Verify**: every command matches its expected result.

### Step 1: Key the venv cache on the pins

1. Read `.github/actions/setup-python-env/action.yml` and list every `cache-key:`
   literal in `.github/workflows/`.
2. Add the pin sources to **every** key:
   `hashFiles('requirements.lock', 'requirements-security.lock', 'Makefile', '.pre-commit-config.yaml')`.
   Rationale to record in a comment where the key is defined: the Makefile holds
   the literal tool pins and `.pre-commit-config.yaml` is the source of truth
   `toolchain-check` compares against, so a pin change must invalidate the cache.
   Trade-off to state explicitly: any Makefile edit now rebuilds the venv cache
   (a ~1-minute cost) — that is the intended, safe direction.

**Verify**: `grep -rn "cache-key:" .github/ | grep -v "Makefile"` → no matches
(every key includes the pins); the YAML parses.

### Step 2: Run the checks in CI

3. Add a step to the `lint` job in `ci.yml` (it already bootstraps):

```yaml
      - name: Toolchain and lock parity
        run: make toolchain-check && make lock-parity-check
```

4. If a different job is a better fit (e.g. `config`), say why in the report; do
   not add a new job for this.

**Verify**: the YAML parses; `grep -n "toolchain-check" .github/workflows/ci.yml`
→ present.

### Step 3: Document the contract

5. `docs/ci.md`: the two checks run in CI; the venv cache key includes the pins
   (and why). Keep the existing structure.

**Verify**: `make docs-check` exits 0.

## Test plan

- No new unit tests: it is a CI/wiring change. Verification is the static matrix
  (every key includes the pins; the step exists; YAML parses) plus the two
  targets passing.
- If the action file supports a default cache key, prove the change reaches it
  (grep the default too).

**Verify**: `make lint && make toolchain-check && make lock-parity-check` → green.

## Done criteria

All must hold:

- [ ] Every `cache-key:` (workflow literals and any default in the action) includes `Makefile` and `.pre-commit-config.yaml`
- [ ] `ci.yml` runs `make toolchain-check && make lock-parity-check` in an existing job
- [ ] All workflow YAML parses
- [ ] `make toolchain-check`, `make lock-parity-check`, `make lint` exit 0
- [ ] `docs/ci.md` documents both
- [ ] `git diff --name-only main...HEAD` lists only in-scope files
- [ ] `plans/README.md` row 158 updated by the reviewer; `make plans-ledger-check` → OK

## STOP conditions

- The action does not use the `cache-key` input for the venv cache (e.g. it keys
  on something else) → report the real key before changing anything.
- Adding `Makefile` to the key would invalidate a cache that other workflows
  share in a way that creates a thrash loop (e.g. jobs that rewrite the Makefile)
  → report; the alternative is a dedicated pins file.
- A job runs without bootstrapping and cannot run the two checks → skip that job
  and say so.

## Maintenance notes

- The invariant: **a cache must never preserve a tool version the pins reject.**
  If the pins ever move out of the Makefile into a dedicated file, update every
  `cache-key` in the same change.
- Reviewer should scrutinise: every key (not just the most visible one) includes
  the pin sources, and the new CI step fails (not warns) on drift.
- **Deferred:** a single `make verify-ci` CI job replacing the per-target jobs.
  Unblocked by a CI-runtime decision.
