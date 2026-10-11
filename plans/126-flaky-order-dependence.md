# Plan 126: Fix order-dependent test pollution (execute the flaky spec)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 04016ca..HEAD -- spec-flaky-tests.md Makefile news_collector/config/settings.py news_collector/observability/enrichment_metrics_store.py tests/e2e_pipeline/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `04016ca`, 2026-10-11
- **Issue**: omit

## Why this matters

The full suite fails intermittently under pytest-randomly, and the
`test-e2e` target papers over a unit→e2e leak with
`--randomly-dont-reorganize` instead of fixing it. Every future test
inherits the ordering hazard, and random seeds red the suite for reasons
unrelated to the change under test. The existing `spec-flaky-tests.md`
already names both root causes as *production* bugs (not test bugs) with
success criteria — this plan executes that spec. Note the related watch
item in the ledger (fifth-pass notes: `test_429_retry_after_handling`
fails under randomized full suite but passes in isolation) — if that
failure appears during verification, record it separately; it is out of
scope here.

## Current state

The spec file exists at repo root and is authoritative for scope:

```md
# spec-flaky-tests.md:1-18 (verified 2026-10-11)
# Spec: Fix pre-existing flaky tests (order-dependent global-state pollution)
## Goals
The full suite fails intermittently under pytest-randomly shuffling. ...
Success criteria:
1. `test_live_refresh` + e2e harness pair is deterministic (was: 3/3 fail).
2. `test_session_reporter` + `test_s1_refactor` never crash on the metrics
   store after any other test closes the singleton.
3. Full suite passes across multiple random seeds (seed 9, 13, 31, …) with
   zero failures attributable to global-state pollution.
4. No new abstractions; production bugs fixed in production code, not in tests.
## Root causes (both are real production bugs, exposed by ordering)
```

```makefile
# Makefile:278-282 — the workaround to remove
@$(PYTEST) tests/e2e_pipeline --no-cov --randomly-dont-reorganize
# (comment: order-sensitive; disables pytest-randomly for the directory)
```

Root causes per the spec: `news_collector/config/settings.py:401`
(`get_config()` returns a snapshot, not the refreshed Config) and
`news_collector/observability/enrichment_metrics_store.py:701/717`
(reads crash on closed connection when `flush()` early-returns).
`settings.py:395-405` verified (refresh choke point with lazy import of
`set_supported_languages` and `return new_snapshot`).

Repo conventions: `docs/AGENTS.md` §4.1 test-quality rules (mock at the
boundary, never the subject); `make test-timeshift` exists for
date-dependent tests (run it as a periodic check, not per-PR).

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Bootstrap | `make bootstrap`         | declared   | exit 0              |
| Unit      | `make test`              | declared   | pass                |
| Seeds     | `pytest -p randomly --randomly-seed=9/13/31 ...` (match repo's pytest invocation in Makefile) | declared | pass on all three seeds |
| E2E       | `make test-e2e`          | declared   | pass (without the workaround flag) |
| Full      | `make test-all`          | declared   | pass                |

## Scope

**In scope** (the only files you should modify):

- `news_collector/config/settings.py` (return the refreshed Config from `get_config()`)
- `news_collector/observability/enrichment_metrics_store.py`
  (`_ensure_open()` on the read paths that crash post-`flush`)
- `Makefile` (remove `--randomly-dont-reorganize` once the leak is fixed)
- `tests/` additions pinning the fixed behaviors (no new abstractions in tests)

**Out of scope** (do NOT touch, even though they look related):

- Any other flaky test (including the `test_429_retry_after_handling`
  watch item — record if seen, don't chase).
- `test-timeshift` gating changes.
- Production behavior beyond the two named bugs (the spec is explicit:
  fix in production code, but only these two).

## Git workflow

- Branch: `advisor/126-flaky-ordering`
- Commit per fix + one for the workaround removal; e.g.
  `fix(config): return refreshed Config from get_config()`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Reproduce

On the unmodified checkout, run the full unit suite three times with
seeds 9, 13, 31 (using the repo's pytest flags from the Makefile `test`
target plus `-p randomly --randomly-seed=N`). Record which seeds fail and
with what errors — confirm they match the spec's described failures
(`test_live_refresh` pair, metrics-store crashes).

**Verify**: at least one seed reproduces the spec's failures (if none
reproduce across the three seeds, STOP and report — the hazard may have
shifted; do not go hunting).

### Step 1: Fix get_config() snapshot bug

Per the spec: return the refreshed Config from `get_config()`. Read
`settings.py:380-410` fully first (lazy-import cycle constraint with
`contracts.collector` is load-bearing — preserve it). Keep
refresh-takes-effect-immediately semantics for every refresh path flowing
through the choke point.

**Verify**: `test_live_refresh` + e2e harness pair deterministic across
seeds 9/13/31; `make test` passes.

### Step 2: Fix metrics-store closed-connection reads

Per the spec: call `_ensure_open()` on the read paths
(`:701/717` — verify exact lines first) so post-`flush` reads reopen
instead of crashing. Preserve the early-return semantics of `flush()`.

**Verify**: `test_session_reporter` + `test_s1_refactor` pass in any order
(prove by running those two files after an unrelated closer test with a
fixed seed); `make test` passes.

### Step 3: Remove the workaround, verify multi-seed

Delete `--randomly-dont-reorganize` from the `test-e2e` target (keep the
comment updated — it should now say the suite is order-safe, with the
date). Run the FULL suite (`make test-all` or the spec's seed matrix)
across seeds 9, 13, 31 with zero global-state-pollution failures.

**Verify**: `make test-e2e` passes without the flag; three seeded full
runs green.

### Step 4: Full gates

Run `make lint && make type && make test`.

**Verify**: all green.

## Test plan

- The spec's own success criteria ARE the test plan (4 items in Current state).
- New regression tests: seed-ordering pair tests pinning both production
  fixes (fail on the original defect — verify by stashing the fix and
  watching them fail, then unstashing).
- Verification: seeds 9/13/31 full-suite green.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "randomly-dont-reorganize" Makefile` returns no matches
- [ ] Three seeded full-suite runs (9, 13, 31) pass with zero ordering failures
- [ ] `make test-e2e` passes without the flag
- [ ] `make lint && make type && make test` pass
- [ ] `git diff --name-only 04016ca...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- No seed reproduces the spec's failures (hazard shifted — report).
- The `get_config()` fix breaks refresh-takes-effect-immediately semantics
  for any refresh path (report which path).
- Callers rely on the snapshot-fallback behavior the spec calls a bug
  (report the callers — operator call, not yours).
- The `test_429_retry_after_handling` watch-item failure appears (record
  it in the commit message verbatim; do not expand scope to fix it).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

For the human/agent who owns this code after the change lands:

- Never re-add `--randomly-dont-reorganize` (or any seed pinning) to work
  around ordering issues — fix the leaked global state instead. The
  three-seed matrix is the cheap periodic check (`make test-timeshift`
  stays separate).
- **Deferred:** none from this plan — the spec's 4 criteria are the whole job.
