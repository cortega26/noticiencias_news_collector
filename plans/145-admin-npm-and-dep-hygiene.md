# Plan 145: Give the admin npm closure a gate, a lock path, and a slimmer runtime set

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 1ff6926..HEAD -- apps/admin/package.json apps/admin/package-lock.json .github/dependabot.yml .github/workflows/ci.yml .github/workflows/dependency-lock-check.yml pyproject.toml requirements.lock requirements-refinery.lock requirements-security.lock scripts/sync_lockfiles.py docs/ci.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW-MED (an eslint plugin major bump can surface new lint findings)
- **Depends on**: plan 143 first (same lock area); **sequence against plans
  138/139/142/144** for the shared CI files
- **Category**: deps
- **Planned at**: commit `1ff6926`, 2026-10-18

## Why this matters

Three dependency-hygiene gaps, all cheap:

1. **`apps/admin` has no advisory coverage.** `npm audit --package-lock-only`
   reports **5 high** advisories, all through the eslint chain:
   `braces@3.0.3` (GHSA-vfj7-8cjw-p6xm, stack-exhaustion DoS, range `<=3.0.3`,
   and upstream has *no* patched braces) → micromatch → fast-glob →
   astro-eslint-parser 1.4.0 → `eslint-plugin-astro` 1.7.0 (declared `^1.5.0`;
   upstream is at 3.x). There is no `npm audit` anywhere in CI, the `Makefile`,
   or `scripts/`, and `.github/dependabot.yml` configures `pip` and
   `github-actions` only — never `npm`. So the repo's only npm surface has no
   automated advisory signal in either direction.
2. **The lock-sync gate ignores one of its three locks.**
   `.github/workflows/dependency-lock-check.yml` triggers on
   `requirements.lock`, `requirements-security.lock`, `pyproject.toml` and itself
   — but the job regenerates **all three** locks
   (`scripts/sync_lockfiles.py`'s `LOCK_TARGETS`) and its cleanliness check
   covers all three. A refinery-lock-only change (or a `refinery` extra change in
   `pyproject.toml`) skips the freshness gate entirely.
3. **Runtime dependencies that are not runtime.** `pyproject.toml:18` declares
   `ruamel.yaml>=0.18.6`, whose only first-party reference is a `try:` fallback in
   `tools/placeholder_audit.py:23` (PyYAML is used first, and both
   `source_catalog_workflow.py` and the tool work with PyYAML). The three
   `types-*` stub packages (`pyproject.toml:34-36`) are mypy-only but sit in
   `[project].dependencies`, so `Dockerfile.serving`'s
   `pip install --require-hashes -r requirements.lock` ships them into the
   production image.

## Current state

- `apps/admin/package.json:36` — `"eslint-plugin-astro": "^1.5.0"`;
  `:13` — `"lint": "prettier --check . && eslint ."`. Node engines `>=24 <25`.
- `.github/dependabot.yml` — two `updates:` entries: `pip` (lockfile-only) and
  `github-actions`. No npm.
- `.github/workflows/ci.yml:127-149` — the `admin-contracts` job
  (`make admin-contracts-check`, `make admin-test`, `make admin-build`).
- `.github/workflows/dependency-lock-check.yml:4-16` — the two `paths:` lists.
- `scripts/sync_lockfiles.py:15` — `LOCK_TARGETS` (three locks) and `:179` the
  regeneration loop; read the file's `--help` for available flags.
- `pyproject.toml:18` — `"ruamel.yaml>=0.18.6",`; `:34-36` — `types-requests`,
  `types-PyYAML`, `types-python-dateutil` in `[project].dependencies`.

## Commands you will need

| Purpose                | Command                                                          | Provenance | Expected on success                |
|------------------------|------------------------------------------------------------------|------------|------------------------------------|
| Admin install          | `make admin-install`                                             | declared   | exit 0                             |
| Admin lint             | `make admin-lint` (from plan 138; `npm --prefix apps/admin run lint` if 138 has not landed) | declared | exit 0 |
| Admin tests/build      | `make admin-test && make admin-build`                            | declared   | exit 0                             |
| npm audit (baseline)   | `cd apps/admin && npm audit --package-lock-only --json \| head -c 800` | executed (advisor ran it: 5 high) | shows the eslint-chain advisories |
| Lint / types / tests   | `make lint && make type && make test`                            | declared   | exit 0                             |
| Lock regen             | `.venv/bin/python scripts/sync_lockfiles.py` (read `--help` first) | declared | clean diff, removals-only churn    |
| Lock check             | `make inventory-check` / `make plans-ledger-check`               | declared   | exit 0 / `validate_plans_ledger: OK` |

Provenance: the `npm audit` row was run by the advisor in this session (read-only;
`--package-lock-only` writes nothing). The rest are `declared`.

## Scope

**In scope**:

- `apps/admin/package.json` + `apps/admin/package-lock.json` (eslint chain bump)
- `.github/dependabot.yml` (npm entry)
- `.github/workflows/ci.yml` **or** a small weekly workflow (npm audit step)
- `.github/workflows/dependency-lock-check.yml` (add the missing path)
- `pyproject.toml` + the three lockfiles (via `scripts/sync_lockfiles.py` only)
- `docs/ci.md` (if a workflow/job is added)

**Out of scope** (do NOT touch):

- `apps/admin` application code and its lint rules
  (`apps/admin/eslint.config.mjs`) — if the plugin bump surfaces new findings,
  report them; do not disable rules.
- `requirements-security.lock`'s contents (plan 143 owns its pin).
- The frontend repo's own npm closure.

## Git workflow

- Branch: `advisor/145-admin-npm-and-dep-hygiene`
- One commit per step; conventional commits, e.g.
  `chore(deps): gate admin npm advisories and drop unused runtime deps (plan 145)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `make admin-install`, `make admin-test`, `make admin-build`, and record
`cd apps/admin && npm audit --package-lock-only --json`'s summary. If admin
install/test/build are already red, STOP and report.

**Verify**: the recorded audit summary and a green admin build.

### Step 1: Add the npm advisory gate and the Dependabot entry

1. Add a step to the admin job in `ci.yml` (or a weekly workflow if you judge
   registry flakiness a risk — state the choice):
   `cd apps/admin && npm audit --audit-level=high` (run after `npm ci`).
2. Add an npm entry to `.github/dependabot.yml`:

```yaml
  - package-ecosystem: "npm"
    directory: "/apps/admin"
    schedule: { interval: "monthly", day: "monday", time: "08:00", timezone: "UTC" }
    open-pull-requests-limit: 3
    rebase-strategy: "disabled"
    commit-message: { prefix: "chore", include: "scope" }
```

3. Document the gate in `docs/ci.md`.

**Verify**: YAML parses; `grep -n "npm audit" .github/workflows/*.yml` shows the step.

### Step 2: Clear the advisories by moving the chain

4. Bump `eslint-plugin-astro` (and `astro-eslint-parser` if it is a direct
   dependency in the lock's chain) to the version that carries a patched
   `braces`/`micromatch`/`fast-glob`, using `npm install --save-dev` (not a
   hand-edit of the lock), then run `make admin-lint`, `make admin-test`,
   `make admin-build`.
   - If the bump surfaces new eslint findings, fix them mechanically
     (`npm --prefix apps/admin run lint-fix`) and report the count; if they are
     semantic, STOP and report.
   - If the bump is blocked (peer conflicts, Astro incompatibility), **stop**:
     keep Step 1's gate but set it to `--audit-level=critical` with a dated
     comment in the workflow explaining the accepted high-severity dev-lint
     advisories, and record both the block and the residual advisory ids in the
     ledger row. Do not silence the gate entirely.
5. Re-run the audit and record the new counts.

**Verify**: `cd apps/admin && npm audit --audit-level=high` → exit 0 (or the
documented, dated residual with `--audit-level=critical`).

### Step 3: Cover the third lock

6. Add `- "requirements-refinery.lock"` to **both** `paths:` lists in
   `.github/workflows/dependency-lock-check.yml`.
7. Optional but preferred: add a `workflow_dispatch` note in the file's header
   comment that `manual-lock-sync` remains the heal path.

**Verify**: the YAML parses; `grep -c "requirements-refinery.lock" .github/workflows/dependency-lock-check.yml` → 2.

### Step 4: Trim the runtime dependency set

8. Before touching anything, read `scripts/sync_lockfiles.py`'s `LOCK_TARGETS`
   to learn how each lock includes extras, and confirm which lock the venv
   bootstrap installs (so that stubs needed by `make type` stay installed).
9. Remove `ruamel.yaml` from `[project].dependencies` (it is unused in
   first-party code except a PyYAML-preferred fallback in a tool). Keep the
   fallback working — PyYAML is a real dependency.
10. Move the three `types-*` stubs out of `[project].dependencies` into the
    existing `test` extra (or a `dev` extra if the lock topology makes that
    cleaner) **only if** the venv still receives them after regeneration. If
    moving them would drop them from the venv, leave them and say so in the
    ledger row (the DoD below gives you the cheap partial credit).
11. Regenerate the locks with the sanctioned script and inspect the diff:
    removals-only, no version churn in unrelated packages. Then run
    `make bootstrap`, `make lint`, `make type`, `make test`.

**Verify**: `.venv/bin/python -c "import importlib.util as u; print(u.find_spec('ruamel'))"` → `None`
in the *runtime* venv is not required (the fallback may resolve it) — what matters
is that `requirements.lock` no longer pins it (or pins it only as a transitive
`# via` of another package) and that `make type` still passes. Record the exact
`# via` line for ruamel after regeneration.

## Test plan

- No new Python tests. The verifications are the audit counts, the admin
  lint/test/build runs, and the lock diff.
- If `tests/test_dependency_lock_sync.py`-style tests exist (grep `tests/` for
  `sync_lockfiles`), run them and keep them green.

**Verify**: `make lint && make type && make test && make admin-test && make admin-build` → green.

## Done criteria

All must hold:

- [ ] `make lint`, `make type`, `make test` exit 0
- [ ] `make admin-test`, `make admin-build`, `make admin-lint` exit 0
- [ ] `npm audit --audit-level=high` exits 0, or a dated, documented residual is
      recorded with `--audit-level=critical` and the advisory ids in the ledger row
- [ ] `.github/workflows/dependency-lock-check.yml` lists all three locks (2 matches)
- [ ] `ruamel.yaml` is out of `[project].dependencies`; the lock diff is
      removals-only (or the STOp reason is recorded)
- [ ] `make inventory-refresh` run if new files/Make targets were added; `make inventory-check` exits 0
- [ ] `git diff --name-only main...HEAD` lists only in-scope files (+ inventory baseline)
- [ ] `plans/README.md` row 145 updated; `make plans-ledger-check` → OK

## STOP conditions

- The eslint-chain bump requires an Astro major upgrade → STOP; report and take
  the documented-residual path from Step 4.
- Regenerating the locks produces churn beyond the removals (e.g. unrelated
  version bumps) → STOP and report the diff; do not commit it.
- Moving the stubs drops them from the venv, breaking `make type` → keep them in
  `[project].dependencies`, record the reason, and take credit for the rest of the
  plan only.

## Maintenance notes

- The npm audit gate will fire again on the next dev-tooling advisory — that is
  the point; the response is a chain bump or a dated, justified threshold change.
- Reviewer should scrutinise: that no eslint rule or lock entry was silenced,
  and that the `types-*` decision matches the lock topology (not a guess).
- **Deferred:** moving the admin app to a pnpm/npm workspaces layout or adding a
  `npm ci --legacy-peer-deps` rationale note in `ci.yml`. Unblocked by nothing;
  not worth doing now.
