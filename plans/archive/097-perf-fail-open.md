# Plan 097: Stop masking perf-suite failures in `make perf`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- Makefile docs/ci.md .github/workflows/ci.yml`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `e77a039`, 2026-09-16

## Why this matters

`make perf` ends with `|| { ...; true; }`, so broken or regressed perf tests
report success, and CI's perf job inherits the mask (`docs/ci.md` openly says
"currently masks pytest failures; inspect artifacts or run pytest directly").
A green perf signal that cannot go red trains reviewers to ignore it and lets
the first real regression slip through. After this plan, collected-test
failures fail the target; only the genuine "no perf tests collected" case
reports a clean skip.

## Current state

The relevant files, each with one line on its role:

- `Makefile` — the `perf` target (lines 283-285)
- `docs/ci.md` — documents the masking (line 32)
- `.github/workflows/ci.yml` — the `perf` job consuming `make perf` (check its failure expectations in Step 1)

Excerpts of the code as it exists today:

`Makefile:283-285`:

```make
perf: bootstrap ## Run performance-focused pytest suite (marked tests)
	@mkdir -p $(PERF_DIR)
	@$(PYTEST) -m "perf" --junitxml=$(PERF_DIR)/junit.xml || { echo "Performance tests not defined; skipped."; touch $(PERF_DIR)/SKIPPED; true; }
```

`docs/ci.md:32`:

```
- `perf` — `make perf` (currently masks pytest failures; inspect artifacts or run pytest directly)
```

Repo conventions that apply here:

- CI guidance in `docs/ci.md`: "run it report-only first… An always-red gate trains everyone to ignore red" — the inverse applies: an always-green gate teaches the same lesson. If unmasking turns the job red on the clean tree, that redness is the finding (see STOP conditions).
- Docs follow code (§9): `docs/ci.md` line 32 must be updated in the same change.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Install   | `make bootstrap`         | declared   | exit 0 |
| Lint      | `make lint`              | declared   | exit 0 |
| Perf      | `make perf`              | declared   | exit 0 iff perf tests pass (after fix) |
| Docs gate | `make docs-check`        | declared   | exit 0 |

## Scope

**In scope** (the only files you should modify):

- `Makefile` (`perf` target only)
- `docs/ci.md` (the masking note only)

**Out of scope** (do NOT touch, even though they look related):

- `.github/workflows/ci.yml` — read it to understand job impact, but do not modify CI wiring in this plan (report the impact instead).
- The perf tests themselves — if they fail when unmasked, that's evidence, not something to "fix" by editing tests (see STOP).
- `make e2e`'s similar `|| true` pattern (line ~281) — same disease, separate decision; report, don't bundle.

## Git workflow

- Branch: `advisor/097-perf-fail-open`
- Conventional commits, e.g. `fix(ci): fail make perf on collected-test failures`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `Install`, then `make perf` on the unmodified checkout and RECORD: exit
code, pytest summary line (passed/failed/error counts), and whether
`reports/perf/SKIPPED` was written. Also read the `perf` job in
`.github/workflows/ci.yml` (~lines 181+) and record whether it tolerates
failure (`continue-on-error`, artifact-only, etc.).

**Verify**: baseline recorded. If `make perf` on the clean tree already runs
real tests that FAIL (masked today), that is the key finding — proceed to
Step 1 anyway (the plan anticipates this), but flag it prominently.

### Step 1: Unmask, keeping a clean no-tests-collected path

Rewrite the recipe so pytest's exit code propagates, except exit code 5 (no
tests collected), which keeps the current skip message + `SKIPPED` marker:

```make
perf: bootstrap ## Run performance-focused pytest suite (marked tests)
	@mkdir -p $(PERF_DIR)
	@$(PYTEST) -m "perf" --junitxml=$(PERF_DIR)/junit.xml; \
	code=$$?; \
	if [ $$code -eq 5 ]; then \
		echo "Performance tests not defined; skipped."; \
		touch $(PERF_DIR)/SKIPPED; \
	elif [ $$code -ne 0 ]; then \
		exit $$code; \
	fi
```

(Careful with Make `$` escaping — `$$?`, `$$code`. Run `make fix-makefile-tabs`
only if you touch recipe indentation; better to match existing tabs exactly.)

Update `docs/ci.md:32` to describe the new behavior (fail on collected-test
failure; clean skip only when zero tests collected).

**Verify**: `make lint` → exit 0 (Makefile tabs check passes); `make perf` exit code now equals the underlying pytest result.

### Step 2: Prove both branches

1. Temporarily (not committed): run the perf selection with a forced failure
   (e.g. `-k` a nonexistent test won't fail — instead run with `--co -q` to see
   collection, then run one known perf test file with an injected env break?).
   Simplest honest proof: `make perf` on the clean tree passes iff the suite
   passes; then `$(PYTEST) -m "perf" --junitxml=/tmp/x.xml -x --lf`? No —
   cleanest: verify exit-code plumbing by running the recipe logic against a
   stub: `sh -c '...; code=$?; ...'` with `true`/`false`/a pytest `--collect-only`
   stand-in. Document what you ran.
2. Confirm `reports/perf/SKIPPED` is written ONLY in the exit-5 case (delete it first, run, check).

**Verify**: exit-code propagation demonstrated for pass (0), fail (nonzero), and empty-collection (5→skip) paths.

### Step 3: Assess CI impact (report, don't change)

Re-read the CI `perf` job: with unmasking, does the job now fail on the current
suite? If the clean-tree suite passes, impact is nil — say so. If it fails,
STOP and report (the suite needs fixing first; this plan must not land a red
perf job — per the repo's own "report-only first" guidance, the follow-up is a
perf-fix plan, not silent test edits here).

**Verify**: written CI-impact statement with job lines cited.

## Test plan

- No new pytest tests (Make/shell change). Verification is exit-code plumbing
  (Step 2) + `make perf` on the clean tree + existing perf suite green.
- `make lint` covers the Makefile-tabs check; `make docs-check` covers the doc edit.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint` and `make docs-check` exit 0
- [ ] `make perf` exit code equals underlying pytest outcome (fail fails, pass passes, empty-collection skips cleanly)
- [ ] `grep -n "|| {" Makefile` → the `perf` mask is gone (report `e2e`'s separately-noted instance, don't touch it)
- [ ] `docs/ci.md` no longer describes perf as masking failures
- [ ] CI-impact statement written in the final report
- [ ] `git diff --name-only e77a039...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- Unmasking reveals the clean-tree perf suite FAILS (report the failures; do not fix tests inside this plan to get green).
- The CI perf job has `continue-on-error: true` or equivalent that makes unmasking a no-op remotely (report; the plan may need a CI follow-up).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- If new perf tests are flaky, quarantine the *test* (skip marker + issue), never re-add a target-level mask.
- Reviewers: the whole value is in the exit code — test it, don't just read it.
- **Deferred:** `make e2e`'s identical `|| true` mask — same recipe, needs its own setup-requirements check first.
