# Plan 156 (revision 2): Install semgrep as an isolated tool, retire the `mcp` exception

> **Revision 2 (2026-10-19).** The original plan moved
> `requirements-security.lock` out of `.venv` and claimed the audit would stop
> seeing `mcp`. **That mechanism cannot work**: `make security-dev` audits the
> **lockfile** (`pip-audit -r requirements-security.lock`, `Makefile:384`), not
> the venv, so relocating the install changes nothing while the lock still
> contains `mcp==1.29.0`. The original plan also left two undeclared
> dependencies: `requirements-security.lock` is the only source of
> **pytest/pytest-cov/pytest-asyncio/coverage/hypothesis/mypy-stubs/pip-audit**
> (the runtime lock has no pytest), and `make bootstrap` installs **bare,
> unpinned `semgrep`** (`.venv`) which pulls `mcp` and forces `click~=8.4.2`
> regardless of the lock. Revision 2 fixes the actual artifact and keeps the dev
> venv intact.
>
> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the next
> step. If anything in the "STOP conditions" section occurs, stop and report —
> do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 003dc87c..HEAD -- pyproject.toml scripts/sync_lockfiles.py requirements-security.lock Makefile scripts/check_lock_parity.py scripts/security_gate.py tests/test_security_gate.py .github/workflows/quality.yml docs/ci.md docs/security.md SECURITY.md .gitignore`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2 (dated exception expires **2026-11-30**)
- **Effort**: S-M
- **Risk**: MEDIUM (build/CI toolchain; a wrong split can silently weaken the audit)
- **Depends on**: 143 (the dated exception), 144 (lock parity), 145 (test-extra stubs), 158 (cache keys)
- **Category**: security / build
- **Planned at**: commit `003dc87c`, 2026-10-19 (revision 2)

## Why this matters

`semgrep` pins `mcp==1.29.0` **exactly** (no release through 1.181.0 lifts it),
and `mcp 1.29.0` carries `GHSA-84m7-p3x7-pcfv`. Plan 143 accepted it as a dated
exception (expiry **2026-11-30**) because the package sits in the audited
`requirements-security.lock`. The durable fix is to stop treating semgrep as an
**audited dependency** and treat it as a **pinned tool**, like `gitleaks`:

- `semgrep` moves out of the `security` extra into its own `sast` extra and its
  own lockfile, installed only in `.venv-security`;
- `requirements-security.lock` (still installed into `.venv` for `security` +
  `test`) becomes **semgrep-free**, so it is clean under `pip-audit` and the
  dated allowlist entry can be deleted;
- the four `lock-parity` collisions (click, pyee, smmap, types-requests) came
  from semgrep's graph; with semgrep out of `.venv`, the exception map empties.

**Deliberate, documented trade-off:** semgrep's own dependency tree is no longer
audited by `security-dev`. It is a dev/CI tool, ships in no image and is pinned
by a hash-pinned lock; the same posture as the gitleaks binary. This must be
written down (Step 4), not left implicit. Revisit when semgrep lifts `mcp`.

## Current state

- `Makefile:95` — `semgrep` (unpinned) in the bootstrap tool list installed into
  `.venv`; `:23-25` — `PIP_AUDIT`/`BANDIT`/`SEMGREP` all use `$(PYTHON_BIN)`
  (`.venv`); `:377-385` — `security-dev` audits
  `pip-audit -r requirements-security.lock`; `:212` and `:233` — semgrep runs in
  `quality` / `quality-ci`.
- `pyproject.toml` — `security = [bandit, pip-audit, semgrep]`; `test` carries
  pytest + stubs (plan 145).
- `scripts/sync_lockfiles.py:15-60` — three `LOCK_TARGETS`; the security target
  deliberately has **no `-c requirements.lock`** with a comment blaming
  semgrep's `click~=8.1.8`. That rationale is stale (1.180/1.181 use
  `click~=8.4.2`) but the constraint is still needed **until semgrep leaves the
  lock**.
- `requirements-security.lock:1195` — `mcp==1.29.0` (via semgrep).
- `scripts/security_gate.py:33-58` — `PIP_AUDIT_ALLOWLIST` with the single dated
  `GHSA-84m7-p3x7-pcfv` entry (the parser/schema fixes from plan 160 are
  unrelated — do not touch them).
- `tests/test_security_gate.py:176-182` — asserts the mcp entry is the only
  active exception; will need to assert an empty set instead.
- `scripts/check_lock_parity.py` — four-entry exception map; ignores packages
  not present in `requirements.lock` (so `test`-extra packages are fine).
- `.github/workflows/quality.yml` — installs gitleaks 8.30.1, runs
  `make quality-ci`, `make quality-gate`, `make security-dev`.
- `.venv` today: `click 8.4.2`, `mcp 1.29.0`, `semgrep 1.180.0`,
  `pytest 9.1.1` (the last one only via the security lock).

## Commands you will need

| Purpose            | Command                                                        | Provenance | Expected on success |
|--------------------|----------------------------------------------------------------|------------|---------------------|
| Bootstrap          | `make bootstrap`                                               | declared   | exit 0              |
| Security env       | `make bootstrap-security`                                      | declared   | exit 0              |
| Lock sync          | `.venv/bin/python scripts/sync_lockfiles.py`                   | declared   | exit 0, only intended diffs |
| Audit (dev lock)   | `make security-dev`                                            | declared   | exit 0, no allowlist |
| Security (runtime) | `make security`                                                | declared   | exit 0              |
| Quality CI         | `make quality-ci`                                              | declared   | exit 0              |
| Parity             | `make lock-parity-check`                                       | declared   | exit 0, 0 exceptions |
| Lint/types/tests   | `make lint` / `make type` / `make test`                        | declared   | exit 0              |
| Docs/inventory     | `make docs-check` / `make inventory-check`                     | declared   | exit 0              |
| Ledger             | `make plans-ledger-check`                                      | declared   | OK                  |

Provenance: all `declared`.

## Scope

**In scope**:

- `pyproject.toml` — `security` loses `semgrep`; new `sast = ["semgrep>=1.60.0"]`
- `scripts/sync_lockfiles.py` — security target gains `-c requirements.lock`
  (now that semgrep is out) and a new `requirements-semgrep.lock` target
  (`--extra sast`, **no** `-c`; it is a standalone tool env)
- `requirements-security.lock`, `requirements-semgrep.lock` (new, regenerate with
  the sanctioned script only)
- `Makefile` — `VENV_SECURITY`/`PYTHON_SECURITY`, `BOOTSTRAP_SECURITY_STAMP`,
  `bootstrap-security`, `SEMGREP` → `.venv-security`, remove bare `semgrep` from
  the `.venv` tool list, add the security-env prerequisite to `quality`,
  `quality-ci` and `security`
- `scripts/security_gate.py` — delete the `GHSA-84m7-p3x7-pcfv` entry and its
  comment block **only**
- `scripts/check_lock_parity.py` — empty the four-entry exception map, keep the
  mechanism and its docs
- `tests/test_security_gate.py` — assert the allowlist is empty
- `.github/workflows/quality.yml` — provision `.venv-security` (+ cache keyed on
  `requirements-semgrep.lock`) before the steps that run semgrep
- `docs/ci.md`, `docs/security.md`, `SECURITY.md` — the two-environment layout,
  the retired exception, and the deliberate audit-scope decision
- `.gitignore` — `.venv-security/`

**Out of scope** (do NOT touch):

- `scripts/security_gate.py`'s pip-audit/bandit/gitleaks parsing logic (plan 160).
- `requirements.lock` / `requirements-refinery.lock` contents.
- Severity thresholds, finder logic, or `--ignore-vuln` flags.
- Dropping `bandit`/`pip-audit` from the `security` extra.

## Git workflow

- Branch: `advisor/156-semgrep-isolated`
- Conventional commits, **one commit per step**; do **not** delete the allowlist
  entry in the same commit as the split (Step 3 is separate so it can be
  reverted independently).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Baseline + confirm the failure mode

1. `make bootstrap`; record `pip show semgrep mcp click` in `.venv` and
   `make lock-parity-check` (expect the four exceptions).
2. Run `.venv/bin/python -m pip_audit -r requirements-security.lock` and confirm
   it reports `mcp 1.29.0` / GHSA-84m7-p3x7-pcfv. This is the artifact the gate
   reads.
3. Confirm nothing imports semgrep:
   `grep -rn "^import semgrep\\|^from semgrep" news_collector scripts tests` → 0.

**Verify**: the audit finding is reproduced; no first-party import.

### Step 1: Split the extras and the locks

4. `pyproject.toml`: move `semgrep>=1.60.0` from `security` to a new `sast` extra.
5. `scripts/sync_lockfiles.py`:
   - security target: add `-c requirements.lock` and remove the stale comment
     about click 8.1.8 (semgrep is no longer in this lock);
   - add a `requirements-semgrep.lock` target: `--no-header --generate-hashes
     --allow-unsafe --extra sast --output-file requirements-semgrep.lock
     pyproject.toml` (**no `-c`** — its graph is deliberately isolated).
6. Run `.venv/bin/python scripts/sync_lockfiles.py`.
   - **STOP** if the security compile is `ResolutionImpossible` (then the
     constraint cannot be restored; report the resolver output).
7. Verify:
   - `grep -c '^semgrep==' requirements-security.lock` → 0
   - `grep -c '^mcp==' requirements-security.lock` → 0
   - `grep -c '^mcp==' requirements-semgrep.lock` → 1 (expected: isolated tool)
   - `git diff` on the two locks shows only semgrep-graph removals plus the
     intended constraint alignment; no unrelated version churn.

**Verify**: the audited lock is semgrep/mcp-free; the tool lock is self-contained.

### Step 2: Isolate the environment

8. `Makefile`: add `VENV_SECURITY ?= .venv-security`, `PYTHON_SECURITY`,
   `BOOTSTRAP_SECURITY_STAMP`, and a `bootstrap-security` target mirroring
   `bootstrap-refinery` (create venv, upgrade pip, install
   `requirements-semgrep.lock` with `--no-deps --require-hashes`, touch stamp).
9. `SEMGREP := $(PYTHON_SECURITY) -m semgrep`; add the security-env stamp as a
   prerequisite of `quality`, `quality-ci` and `security` (whichever runs
   semgrep); leave `PIP_AUDIT`/`BANDIT` on `.venv` (their pins are the
   pre-commit/toolchain ones — moving bandit would create a 1.7.9/1.9.4 skew).
10. Remove the bare `semgrep` token from the `.venv` bootstrap tool list.
11. `.gitignore`: add `.venv-security/`.
12. Prove a clean dev venv: `rm -rf .venv && make bootstrap`, then
    `.venv/bin/python -c "import importlib.util as u; print(u.find_spec('semgrep'), u.find_spec('mcp'))"`
    → `None None`, and `.venv-security/bin/python -m semgrep --version` works.

**Verify**: dev venv has no semgrep/mcp; tool venv has semgrep.

### Step 3: Retire the exception (separate commit)

13. Delete the `GHSA-84m7-p3x7-pcfv` entry and its comment block from
    `PIP_AUDIT_ALLOWLIST`; leave the expiry machinery intact.
14. Empty the four-entry exception map in `scripts/check_lock_parity.py`.
15. Update `tests/test_security_gate.py` to assert an **empty** allowlist (keep
    the expiry-machinery tests).
16. Run `make security-dev` (must be green **without** any entry),
    `make security`, `make lock-parity-check`, `make quality-ci`
    (semgrep now runs from `.venv-security`).
    - **STOP** if any HIGH finding appears in the regenerated security lock;
      report it — do not add an entry.
    - **STOP** if lock-parity needs an exception; report the package.

**Verify**: all three green; `grep -c 'GHSA-84m7' scripts/security_gate.py` → 0.

### Step 4: CI and documentation

17. `.github/workflows/quality.yml`: add `make bootstrap-security` before the
    quality/security steps; add an actions/cache entry for `.venv-security`
    keyed on `hashFiles('requirements-semgrep.lock')` (mirror the composite
    action's cache style). Verify the YAML parses.
18. `docs/ci.md`, `docs/security.md`, `SECURITY.md`: the two-environment layout,
    why (semgrep's exact `mcp` pin; no release lifts it), the retired exception,
    and the **explicit** audit-scope decision: semgrep's own tree is installed
    from a hash-pinned lock but is not audited, same posture as gitleaks.
19. `make docs-check`, `make inventory-refresh && make inventory-check`,
    `make plans-ledger-check`.

**Verify**: docs green; inventory drift 0.

### Step 5: Full gates

20. `make lint`, `make type` (post-commit), `make test`,
    `make test-boundaries`, `make test-contracts`, `make toolchain-check`,
    `make lock-parity-check`, `make security`, `make security-dev`,
    `make quality-ci`, `make docs-check`, `make inventory-check`,
    `make plans-ledger-check`.
21. Record the final `.venv` vs `.venv-security` package split and the lock
    diffs in NOTES.

**Verify**: all exit 0.

## Test plan

- `tests/test_security_gate.py` — empty allowlist assertion (updated).
- `tests/scripts/test_sync_lockfiles.py` — extend for the fourth target if it
  enumerates `LOCK_TARGETS`; run it.
- Behavioural evidence: `security-dev` green without an exception; a clean
  bootstrap installs no semgrep/mcp in `.venv`.

**Verify**: `make test` green.

## Done criteria

All must hold:

- [ ] `grep -c '^mcp==' requirements-security.lock` → 0; `^semgrep==` → 0
- [ ] `requirements-semgrep.lock` exists, hash-pinned, installs in `.venv-security`
- [ ] clean `.venv` has no `semgrep`/`mcp`; `.venv-security` runs semgrep
- [ ] `make security-dev`, `make security`, `make lock-parity-check`, `make quality-ci` exit 0 with **no** allowlist entry and **no** parity exception
- [ ] `make lint`, `make type`, `make test`, `make test-boundaries`, `make test-contracts`, `make toolchain-check`, `make docs-check`, `make inventory-check`, `make plans-ledger-check` exit 0
- [ ] CI YAML parses and provisions `.venv-security`
- [ ] Docs state the deliberate audit-scope decision (no "accepted risk" claim left)
- [ ] `git diff --name-only main...HEAD` lists only the in-scope files
- [ ] Ledger row 156 updated by the reviewer

## STOP conditions

- The security lock compiles `ResolutionImpossible` with `-c requirements.lock`
  (the split cannot be done as designed).
- The regenerated `requirements-security.lock` still contains `mcp` or any
  semgrep transitive, or `pip-audit` reports a **new** HIGH finding.
- The clean `.venv` still gets `semgrep`/`mcp` from some other path (e.g. a
  remaining unpinned install).
- `lock-parity-check` needs a new exception.
- Anything requires dropping a rule/severity, disabling a gate, or touching
  `requirements.lock`.
- CI cannot provision the second environment within the job's timeout.

## Rollback

Revert the branch and restore the dated exception on `main` with a **new**
expiry (e.g. 2027-01-31) and a pointer to this plan; do not leave main with a
failing gate or a silently weakened one.

## Maintenance notes

- semgrep is now a **tool**, not an audited dependency. If its own tree needs
  auditing, re-add it to an audited lock — which re-introduces the `mcp`
  exception until upstream lifts the pin.
- Keep the `.venv-security` cache keyed on `requirements-semgrep.lock`; a stale
  cache with the old semgrep is harmless (it is not imported by tests) but will
  hide upgrades.
- Reviewer should scrutinise: no allowlist entry remains, no parity exception
  remains, `.venv` is semgrep-free on a clean bootstrap, and the docs say the
  trade-off out loud.
