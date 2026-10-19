# Plan 162: Cover the fourth lock in the freshness gate and the heal workflow

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 432e57b8..HEAD -- .github/workflows/dependency-lock-check.yml .github/workflows/manual-lock-sync.yml docs/ci.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2 (silent gap in a lock gate)
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 156 (added `requirements-semgrep.lock`)
- **Category**: CI / supply chain
- **Planned at**: commit `432e57b8`, 2026-10-19

## Why this matters

Plan 156 added a fourth hash-pinned lock, `requirements-semgrep.lock` (the
isolated semgrep tool environment), and `scripts/sync_lockfiles.py --check` now
covers it. Two workflows still assume **three** locks:

1. `.github/workflows/dependency-lock-check.yml` — the header says "all three
   hash-pinned lockfiles" and neither `paths:` list includes
   `requirements-semgrep.lock`. A PR that edits only the new lock skips the
   freshness gate entirely.
2. `.github/workflows/manual-lock-sync.yml` — the heal path diffs and commits
   only the original three (`:42`, `:57`). If a heal regenerates all four locks,
   the new one is left dirty and the workflow commits an incomplete state.

Neither is exploited today (no one has edited the new lock since 156), but both
are exactly the kind of silent coverage gap the last passes kept finding.

## Current state

- `scripts/sync_lockfiles.py` — `LOCK_TARGETS` has **four** entries after plan
  156 (`requirements.lock`, `requirements-refinery.lock`,
  `requirements-security.lock`, `requirements-semgrep.lock`); `--check`
  validates all four.
- `.github/workflows/dependency-lock-check.yml` — header comment at `:1`
  ("three"); `paths:` lists at `:6-13` (push) and `:15-22` (pull_request) name
  three locks.
- `.github/workflows/manual-lock-sync.yml:42` — `git diff --quiet --
  requirements.lock requirements-refinery.lock requirements-security.lock`;
  `:57` — `git add` with the same three.
- `docs/ci.md` — describe the lock workflow (grep for "lock" and update the
  count/list if it enumerates them).

## Commands you will need

| Purpose        | Command                                                    | Provenance | Expected |
|----------------|------------------------------------------------------------|------------|----------|
| Install        | `make bootstrap`                                           | declared   | exit 0   |
| Lock check     | `.venv/bin/python scripts/sync_lockfiles.py --check`        | declared   | exit 0   |
| Docs           | `make docs-check`                                          | declared   | exit 0   |
| Inventory      | `make inventory-refresh && make inventory-check`            | declared   | exit 0   |
| Ledger         | `make plans-ledger-check`                                  | declared   | OK       |

Provenance: all `declared`.

## Scope

**In scope**: `.github/workflows/dependency-lock-check.yml`,
`.github/workflows/manual-lock-sync.yml`, `docs/ci.md` (the lock section only).

**Out of scope**: `scripts/sync_lockfiles.py` (already correct), any lock
contents, any other workflow.

## Steps

1. `dependency-lock-check.yml`: add `- "requirements-semgrep.lock"` to **both**
   `paths:` lists and change the header "three" → "four" (name the four files).
2. `manual-lock-sync.yml`: add `requirements-semgrep.lock` to the `git diff`
   guard and to the `git add` line; update any comment that says "three".
3. `docs/ci.md`: if it enumerates the locks, add the new one and the reason
   (isolated semgrep tool env from plan 156); if it points at the script, make
   the count match.
4. Verify:
   - `grep -c "requirements-semgrep.lock" .github/workflows/dependency-lock-check.yml` → **2**
   - `grep -c "requirements-semgrep.lock" .github/workflows/manual-lock-sync.yml` → **2**
   - YAML parses for both files (`python3 -c "import yaml; yaml.safe_load(open(...))"`)
   - `.venv/bin/python scripts/sync_lockfiles.py --check` → exit 0
   - `make docs-check`, `make inventory-refresh && make inventory-check`,
     `make plans-ledger-check` → green
5. Commit as `ci(locks): cover requirements-semgrep.lock in the freshness and heal workflows (plan 162)`.

## Done criteria

- [ ] Both workflows name all four locks (2 occurrences each)
- [ ] YAML parses; docs-check, inventory-check, ledger green
- [ ] `git diff --name-only main...HEAD` lists only the three in-scope files
- [ ] Ledger row 162 updated by the reviewer

## STOP conditions

- `manual-lock-sync.yml` regenerates locks with a different command than
  `scripts/sync_lockfiles.py` (then the commit list may differ — report).
- `docs/ci.md` cannot be updated without touching the semgrep design text from
  156 (report; do not rewrite the trade-off paragraph).
