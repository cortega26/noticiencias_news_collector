# Plan 138: Gates must not report success while skipping or swallowing work

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 1ff6926..HEAD -- Makefile .github/workflows/ci.yml docs/ci.md .pre-commit-config.yaml apps/admin/package.json`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none, but **sequence against plans 137, 139, 143, 144, 145** —
  all touch the `Makefile` and/or `.github/workflows/ci.yml`; run them one at a
  time, each merged before the next starts
- **Category**: tests / dx
- **Planned at**: commit `1ff6926`, 2026-10-18

## Why this matters

Three advertised gates can return success while doing nothing:

1. `make e2e` — `|| { echo "E2E tests require additional setup and were skipped."; true; }`
   swallows **every** non-zero exit, including real assertion failures. The
   sibling `make perf` already has the correct shape (plan 097 fixed exactly this
   disease there and deferred this half).
2. `make security` — the gitleaks leg is silently skipped when the binary is
   absent (`echo "... skipping secret scan (CI installs it)"`), and `security` is
   part of `verify-ci`. A clean local `make verify-ci` can therefore report a
   green secret scan that never ran.
3. The admin app's own lint (`prettier --check` + `eslint` with `no-secrets` and
   `eslint-plugin-security`) runs **only** in the local pre-commit hook — there
   is no Make target and no CI step, so a GitHub web edit, a `--no-verify`
   commit, or a clone without `node_modules` merges admin violations with green
   CI.

## Current state

- `Makefile:303-304`:

```make
e2e: bootstrap ## Run end-to-end pytest suite (marked tests)
	@$(PYTEST) -m "e2e" || { echo "E2E tests require additional setup and were skipped."; true; }
```

- `Makefile:306-315` — the correct pattern to copy (`perf`): captures `$$?`,
  treats exit **5** (nothing collected) as a clean skip with a `SKIPPED` marker
  under `$(PERF_DIR)`, and re-exits any other code.
- `Makefile:328-334` — the security recipe, ending in:

```make
	@if command -v gitleaks >/dev/null 2>&1; then \
		gitleaks detect ... ; \
		$(PYTHON_BIN) scripts/security_gate.py gitleaks $(GITLEAKS_REPORT) --severity HIGH --status $(SECURITY_STATUS); \
	else \
		echo "[security] gitleaks not installed; skipping secret scan (CI installs it)."; \
	fi
```

- `.pre-commit-config.yaml:34-39` — the only place the admin lint runs:

```yaml
      - id: admin-lint
        name: admin lint (prettier + eslint)
        entry: npm --prefix apps/admin run lint
        language: system
        files: ^apps/admin/
        pass_filenames: false
```

- `apps/admin/package.json:13` — `"lint": "prettier --check . && eslint ."`.
- `.github/workflows/ci.yml:127-149` — the `admin-contracts` job runs
  `make admin-contracts-check`, `make admin-test`, `make admin-build` — **no lint**.
- `docs/ci.md:25-38` — the job list that must stay true after this change.

## Commands you will need

| Purpose            | Command                                                       | Provenance | Expected on success            |
|--------------------|---------------------------------------------------------------|------------|--------------------------------|
| Install/baseline   | `make bootstrap`                                              | declared   | exit 0                         |
| Lint               | `make lint`                                                   | declared   | exit 0                         |
| Types + coverage   | `make type`                                                   | declared   | exit 0                         |
| Admin lint (new)   | `make admin-lint`                                             | declared   | exit 0                         |
| Security gate      | `make security`                                               | declared   | exit 0 with gitleaks present   |
| Ledger             | `make plans-ledger-check`                                     | declared   | `validate_plans_ledger: OK`    |

Provenance: all `declared` (advisor read the `Makefile`, the workflow and the
hook; the advisor ran none of them).

## Scope

**In scope**:

- `Makefile` — the `e2e` and `security` recipes, plus a new `admin-lint` target
- `.github/workflows/ci.yml` — one step in the existing `admin-contracts` job
- `docs/ci.md` — job list/`gate` descriptions and the opt-out documentation
- `CONTRIBUTING.md` — only if it advertises `make e2e` or the security target

**Out of scope** (do NOT touch):

- `make perf` (already correct).
- The e2e test selection or any test file.
- `scripts/security_gate.py` (its behaviour is correct; only the Makefile's
  handling of the missing binary changes).
- The pre-commit hook itself (it stays; CI gains parity).
- `make verify-ci`'s composition — it already depends on `security`; no change.

## Git workflow

- Branch: `advisor/138-gate-honesty`
- Conventional commit, e.g. `fix(make): stop masking e2e failures and gitleaks skips (plan 138)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `make bootstrap`, `make lint`, `make type`, and `make security` on the
unmodified checkout. Red baseline → STOP and report (note: `make security` may
be red for reasons unrelated to this plan if a secret scan or audit finding is
open — report if so; plans 143 owns the pip-audit side).

**Verify**: every command's outcome recorded, including `command -v gitleaks`.

### Step 1: Unmask `make e2e`

1. Copy the `perf` recipe's structure, keeping the existing marker convention:

```make
e2e: bootstrap ## Run end-to-end pytest suite (marked tests)
	@mkdir -p $(E2E_DIR)
	@$(PYTEST) -m "e2e" --junitxml=$(E2E_DIR)/junit.xml; \
	code=$$?; \
	if [ $$code -eq 5 ]; then \
		echo "E2E tests not defined; skipped."; \
		touch $(E2E_DIR)/SKIPPED; \
	elif [ $$code -ne 0 ]; then \
		exit $$code; \
	fi
```

   Reuse the existing `$(PERF_DIR)` convention's directory variable name pattern
   (`E2E_DIR` must be defined next to it — check the top of the Makefile).

2. Prove both branches without touching test files:
   - clean skip: `.venv/bin/pytest -m "e2e and __no_such_marker__"` exits 5 → the
     recipe's skip branch prints and exits 0 (simulate by running the recipe with
     a temporarily narrowed expression, or by running the shell snippet directly
     and documenting it);
   - failure propagation: run the snippet with a command that exits 1 (e.g.
     replace `$(PYTEST) …` with `false` in a scratch copy of the recipe) → the
     snippet exits 1. Record both observed exit codes.

**Verify**: `make e2e` exits 0 on a green tree (or exits with pytest's real code if
the suite is red — that is now correct behaviour); the two branch proofs are
recorded.

### Step 2: Make the missing secret scanner loud

3. Change the `else` branch to fail unless explicitly opted out:

```make
	@if command -v gitleaks >/dev/null 2>&1; then \
		gitleaks detect ... ; \
		$(PYTHON_BIN) scripts/security_gate.py gitleaks $(GITLEAKS_REPORT) --severity HIGH --status $(SECURITY_STATUS); \
	elif [ "$${SKIP_SECRET_SCAN:-0}" = "1" ]; then \
		echo "[security] secret scan skipped by SKIP_SECRET_SCAN=1"; \
	else \
		echo "[security] gitleaks not installed; install it or set SKIP_SECRET_SCAN=1 to skip explicitly" >&2; \
		exit 1; \
	fi
```

4. Document the opt-out in `docs/ci.md` (one line) and mention where to get the
   binary/version (CI pins `GITLEAKS_VERSION=8.30.1` in
   `.github/workflows/quality.yml:44-58` — point at it, do not duplicate the pin).

**Verify**: with gitleaks absent from `PATH`
(`env PATH=/tmp/nogitleaks:/usr/bin:/bin make security`) → exit 1 and the message;
with `SKIP_SECRET_SCAN=1` → exit 0 and the skip line. Record both outputs.

### Step 3: Bring the admin lint into CI

5. Add `admin-lint: ## Lint the Astro admin app (prettier + eslint)` with
   `@cd apps/admin && npm run lint` (match how `admin-test`/`admin-build` are
   written — see `Makefile:137-141`).
6. Add a step to the existing `admin-contracts` job in `ci.yml`:
   `- name: Admin lint` / `run: make admin-lint` (after `make admin-test`).
7. Update `docs/ci.md`: the `admin-contracts` description and the job list must
   mention the lint step.

**Verify**: `make admin-lint` exits 0 on the unmodified tree. If it fails, the
hook has been bypassed at some point — fix only whitespace/formatting issues with
`npm --prefix apps/admin run lint-fix` and re-run; if real eslint errors remain,
STOP and report them (do not silence rules).

## Test plan

- No new Python tests. The verifications are the recorded branch proofs above.
- Add nothing to `.pre-commit-config.yaml`.

**Verify**: `make lint && make type` → green (Makefile tabs check included); CI
YAML parses.

## Done criteria

All must hold:

- [ ] `make lint`, `make type` exit 0
- [ ] `make e2e`'s recipe no longer contains `|| { echo` or a bare `true` fallback
- [ ] Missing-gitleaks proof recorded (exit 1 without the opt-out, exit 0 with it)
- [ ] `make admin-lint` exists and exits 0; CI step present; `docs/ci.md` updated
- [ ] `make inventory-refresh` run if the Make target count changed; `make inventory-check` exits 0
- [ ] `git diff --name-only main...HEAD` lists only in-scope files (+ inventory baseline)
- [ ] `plans/README.md` row 138 updated; `make plans-ledger-check` → OK

## STOP conditions

- `make admin-lint` fails on the unmodified tree with non-formatting errors →
  report (this is a pre-existing debt finding, not something to silence).
- Removing the e2e mask turns a currently-masked **real** failure into a red
  target on an unmodified checkout → report both the failure and its history
  rather than re-adding the mask.
- `gitleaks` turns out to be installed in the executor's environment such that no
  branch can be exercised → say so and verify by reading the recipe instead, and
  mark the proof as static in the ledger row.

## Maintenance notes

- `SKIP_SECRET_SCAN=1` is the only sanctioned way to skip; if a future workflow
  sets it globally, that is a regression — grep the workflows when reviewing.
- Reviewer should scrutinise: that no other Make target still contains a `|| true`
  that hides a real failure (`grep -n "|| true\|; true;" Makefile` — report, do
  not fix, anything outside scope).
- **Deferred:** running the admin lint in the pre-push hook as well as CI.
  Unblocked by nothing; not needed while CI covers it.
