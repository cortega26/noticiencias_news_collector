# Plan 129: Backend DX and docs (enforced gates, admin tooling, stale prose)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 04016ca..HEAD -- Makefile .pre-commit-config.yaml pyproject.toml apps/admin/package.json CLAUDE.md docs/security.md docs/INDEX.md spec-alt-text-brief-flow.md spec-curation-desk-revamp.md todo-webhook-inbox-deploy.md docs/RUNBOOK_LOCAL_DEV.md news_collector/serving/api.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none (coordinate with plan 081's docs reconciliation —
  it owns governance files; this plan touches leaf rows + entry docs.
  If 081 is actively editing the same files, sequence after it.)
- **Category**: dx
- **Planned at**: commit `04016ca`, 2026-10-11
- **Issue**: omit

## Why this matters

The backend's gates diverge from what contributors actually run: import
order is owned-but-unenforced in CI (pre-commit only), the "type" gate
checks 3 files, the current Astro admin GUI has zero lint/format story,
`CLAUDE.md` misdescribes both gates (agents under-run them), the serving
API has no request correlation while the pipeline enjoys `trace_id`s, and
four stale-prose defects send operators to nonexistent flags, wrong ADRs,
and orphaned spec/todo halves. All additive or prose-only; each makes the
next contributor (human or agent) faster or more correct.

Boundary notes (read before scoping): the fifth-pass ledger deferred the
"3-file mypy scope" widening and the "`make type` double-suite cost" as
second-tier — this plan does NOT widen mypy targets or restructure
`type`/`test` (recorded as deferred in Maintenance). It adds the missing
isort enforcement (new, never deferred) and leaves mypy alone.

## Current state

Facts (all verified 2026-10-11):

```makefile
# Makefile:167-172 — lint has no isort
lint: bootstrap ## Run code quality checks (check-only)
	@$(PYTHON_BIN) tools/check_makefile_tabs.py Makefile
	@$(BLACK) --check .
	@$(RUFF) check .
	@$(MAKE) check-deprecated
# .pre-commit-config.yaml:21-25 runs isort as a local hook only;
# .github/workflows/ci.yml:18-29 lint job runs `make lint` only.
# pyproject.toml:90-93 comment names isort the import-order owner.
```

```json
// apps/admin/package.json:6-16 — no eslint/prettier/lint script
"scripts": { "dev", "build", "preview", "test", "test:watch", "astro",
  "check", "contracts:generate", "contracts:check" }
// .pre-commit hooks are Python-scoped (files: ^news_collector/); no backend
// .editorconfig or .nvmrc at root (frontend has both); apps/admin has no
// `engines` field; backend CI uses Node 24 (ci.yml:107-110) with no local pin.
```

```md
# CLAUDE.md:15-17 — wrong on both lines
make lint             # ruff + black + isort     <- isort NOT in make lint
make type             # mypy strict              <- 3-file allowlist + ratchet
# Root AGENTS.md:21-37 documents both accurately (the fix copies its wording).
```

```python
# serving/api.py:898-908 — only CORSMiddleware wired; no request/correlation ID
# anywhere in serving/, apps/admin/src/, workers/src/ (grep-verified).
# Contrast system/observability.py:15-164 + utils/logger.py:224-235 (trace_id/session_id).
```

```md
# docs/security.md:18,22 (verified) — claims make security-dev "audits ...
# with a hardcoded protobuf advisory ignore" + expiry enforcement "does not
# cover security-dev's separate CLI ignore". Makefile:188-189,333-337 show
# exceptions live only in scripts/security_gate.py (PIP_AUDIT_ALLOWLIST);
# SECURITY.md:38-42 records the inline --ignore-vuln flag retired 2026-09-16
# for an allowlist entry expiring 2026-10-31 (scripts/security_gate.py:33-44).
# docs/INDEX.md:50 — labels security_removal_plan.md "(expired; ...)" though
# the plan tracks the live 2026-10-31 entry (SECURITY.md:25-26 confirms current).
```

Orphaned governance halves (verified by listing): `spec-alt-text-brief-flow.md`
(no todo), `spec-curation-desk-revamp.md` (no todo),
`todo-webhook-inbox-deploy.md` (no spec). `docs/AGENTS.md` §0.1 requires
spec+todo together.

```makefile
# Makefile:123-124 — admin-install uses `npm install` (unpinned)
admin-install: ## Install the new Refinery admin GUI (Astro app in apps/admin/)
	@cd apps/admin && npm install
# docs/RUNBOOK_LOCAL_DEV.md:19 prescribes `npm --prefix apps/admin ci`.
# RUNBOOK_LOCAL_DEV.md:50 accurately notes make admin/serve don't run migrate (easy to skip).
```

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Bootstrap | `make bootstrap`         | declared   | exit 0              |
| Lint      | `make lint`              | declared   | exit 0              |
| Docs check | `make docs-check`       | declared   | exit 0              |
| Admin check | `make admin-build` / `admin-test` (verify names in Makefile first) | declared | pass |
| Ledger    | `make plans-ledger-check` | declared  | exit 0 (README edits must stay valid) |

## Scope

**In scope** (the only files you should modify):

- `Makefile` (`lint` += isort check; `admin-install` → `npm ci`)
- `.pre-commit-config.yaml` (apps/admin stanza)
- `apps/admin/` (eslint+prettier devDeps, `lint`/`lint-fix` scripts —
  mirror the frontend root config)
- `CLAUDE.md` (two-line correction)
- `news_collector/serving/api.py` (request-ID middleware ONLY — one
  middleware + log-context binding)
- `docs/security.md`, `docs/INDEX.md` (prose fixes)
- The three orphan spec/todo halves (create counterparts or archive with a note)
- `docs/RUNBOOK_LOCAL_DEV.md` (migrate hint — short addition only)
- Root `.editorconfig`, `.nvmrc`, `apps/admin/package.json` `engines`

**Out of scope** (do NOT touch, even though they look related):

- `MYPY_TARGETS` widening — deferred by prior ledger decision.
- `type`/`test` double-suite restructure — deferred by prior decision.
- Plan 081-owned governance files (`docs/AGENTS.md`, `SOURCE_OF_TRUTH.md`,
  `ARCHITECTURE.md`, `PIPELINE_CONTRACTS.md`) — coordinate, don't compete.
- Admin auth protocol changes — plan 123 owns the security side.

## Git workflow

- Branch: `advisor/129-backend-dx-docs`
- Commit per item; e.g. `chore(dx): enforce isort in make lint`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Baseline + plan-081 coordination check

Run `make lint && make docs-check && make plans-ledger-check`. Check plan
081's todo for active edits to `docs/security.md`, `docs/INDEX.md`,
`CLAUDE.md`, `RUNBOOK_LOCAL_DEV.md` — if it owns them right now,
sequence this plan's docs items after it (do the DX-code items first).

**Verify**: gates green; coordination noted in the first commit message.

### Step 1: Enforce isort + admin-install pinning

1. Add `isort --check-only --diff` (same settings path as the pre-commit
   args) to the `lint` recipe. First run may surface pre-existing
   violations — if so, STOP and report them (don't bulk-fix unrelated
   files in this plan; fix only files already in scope, or report).
2. `admin-install`: `npm install` → `npm ci` (lockfile exists in
   `apps/admin/` — verify first; if absent, STOP).

**Verify**: `make lint` green; `make admin-install` (dry-run read of the
recipe if network is restricted) resolves to `npm ci`.

### Step 2: Admin lint story + editor/JS tooling

1. Port `eslint.config.mjs` + `.prettierrc` approach into `apps/admin`
   (add devDeps, `lint`/`lint-fix` scripts), add a pre-commit stanza for
   `apps/admin/`.
2. Add root `.editorconfig` (copy-adapt frontend's), `"engines":
   {"node": ">=24 <25"}` to `apps/admin/package.json`, mirror `.nvmrc`
   (`24`, matching CI `ci.yml:107-110`).

**Verify**: `make admin-build` green; new lint script runs clean on the
admin tree (baseline violations, if any, reported not bulk-fixed).

### Step 3: Request-ID middleware + CLAUDE.md fix

1. Starlette middleware: accept-or-mint `X-Request-ID`, store on
   `request.state`, bind to the loguru context for the request lifetime
   (follow the `system/observability.py` trace_id pattern for the binding).
   No behavior change otherwise.
2. Rewrite the two `CLAUDE.md` annotations to match root `AGENTS.md`
   wording (`make lint # black --check + ruff (+ isort via pre-commit
   only)` — update post-Step-1 to say isort enforced; `make type # mypy
   3-file allowlist + unit coverage ratchet`).

**Verify**: `make test-boundaries` passes (middleware covered by a test
asserting header echo + log binding); `CLAUDE.md` matches `AGENTS.md`.

### Step 4: Stale prose + orphans + runbook hint

1. `docs/security.md`: rewrite the `security-dev` row (evaluates through
   `PIP_AUDIT_ALLOWLIST` like every pip-audit leg) and delete/adjust the
   "does not cover" sentence.
2. `docs/INDEX.md`: relabel the removal-plan row active/time-bounded
   (`active until 2026-10-31`).
3. Orphans: for each of the three, either create the counterpart from the
   existing file's scope or archive/remove with a one-line ledger note —
   confirm with the file's recency/owner context first (don't invent
   scope for a spec whose work was superseded; check `plans/README.md`
   for references).
4. Runbook: align on `npm ci` + add a startup hint for pending migrations.

**Verify**: `make docs-check` green; `make plans-ledger-check` green.

## Test plan

- Middleware test (header echo/mint + context binding).
- No other new tests (config + prose). `make docs-check` is the docs verification.
- Verification: `make lint` (with isort) + `make test-boundaries` + `make docs-check` green.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "isort" Makefile` shows a check in the `lint` recipe
- [ ] `grep -n "npm ci" Makefile` in `admin-install` (not bare `npm install`)
- [ ] `apps/admin/package.json` has `lint` script + `engines`; root `.editorconfig` + `.nvmrc` exist
- [ ] `X-Request-ID` middleware present with a test
- [ ] `docs/security.md` no longer mentions a "hardcoded ignore"/"separate CLI ignore"
- [ ] `docs/INDEX.md` no longer labels the removal plan "expired"
- [ ] No orphan spec/todo halves remain (or ledger-noted removals)
- [ ] `make lint && make test-boundaries && make docs-check && make plans-ledger-check` all pass
- [ ] `git diff --name-only 04016ca...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- Step-1 isort surfaces pre-existing violations (report; don't bulk-fix).
- Plan 081 actively owns the same docs files (sequence, don't compete).
- An orphan's counterpart can't be scoped honestly (archive + note instead of inventing).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

For the human/agent who owns this code after the change lands:

- New JS/TS under `apps/admin/` is now linted pre-commit — keep the hook's
  file filter in sync if the admin tree gains new extensions.
- **Deferred (prior ledger decisions, standing):** mypy target widening;
  `type`/`test` double-suite restructure. Revisit only with new evidence
  and a ledger note.
