# Plan 156: Decouple semgrep from the audited environment (retire the `mcp` exception)

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat bc3b38a4..HEAD -- Makefile .github/actions/setup-python-env .github/workflows/quality.yml .gitignore scripts/security_gate.py scripts/check_lock_parity.py SECURITY.md docs/security.md docs/ci.md requirements-security.lock`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (touches the security toolchain and CI provisioning)
- **Depends on**: plan 144 (DONE — the lock-parity check it introduces is the safety net for this split); **deadline: before 2026-11-30** (the `mcp` allowlist expiry)
- **Category**: security / deps
- **Planned at**: commit `bc3b38a4`, 2026-10-19

## Why this matters

`make bootstrap` installs **both** `requirements.lock` and
`requirements-security.lock` into the same `.venv`, so the dev/security lock
silently overrides four runtime pins (click, pyee, smmap, types-requests). Plan
144 makes that drift visible (`make lock-parity-check` with a dated exception
map), but the drift itself remains.

The reason the security lock exists in the same environment is `semgrep`, whose
own dependency graph is incompatible with the runtime tree: semgrep 1.180.0 pins
`click~=8.1.8`, while scrapling needs `click>=8.3.0`, and semgrep **also pins
`mcp==1.29.0` exactly** — the advisory `GHSA-84m7-p3x7-pcfv` that plan 143 had to
accept as a **dated exception** (expiry **2026-11-30**) because no semgrep release
through 1.181.0 lifts the pin.

The durable fix is to stop installing the security toolchain into the runtime
venv: give it its own environment (the repo already does exactly this for the
legacy refinery UI with `.venv-refinery`). Then the runtime venv matches
`requirements.lock` byte-for-byte, the audit no longer sees semgrep's dev-only
`mcp`, and **the allowlist entry can be deleted**.

## Current state

- `Makefile:79-82` — the bootstrap install order (runtime lock, then the security
  lock, then the unpinned/pinned tool list). `$(VENV_REFINERY)` /
  `bootstrap-refinery` is the precedent for a second environment.
- `Makefile` variables: `PIP_AUDIT := $(PYTHON_BIN) -m pip_audit`,
  `BANDIT := $(PYTHON_BIN) -m bandit`, `SEMGREP := $(PYTHON_BIN) -m semgrep`;
  `security` / `security-dev` / `quality` / `quality-ci` use them.
- `scripts/security_gate.py` — one dated allowlist entry
  (`GHSA-84m7-p3x7-pcfv`, `mcp` via semgrep's exact pin, `expires_on:
  2026-11-30`, reason naming plan 144 as the durable fix). **This plan retires
  it.**
- `.github/actions/setup-python-env/action.yml` — provisions `.venv` from the
  lock hashes; the quality workflow installs the security tools through
  `make bootstrap`.
- `scripts/check_lock_parity.py` (plan 144) — compares the runtime venv against
  `requirements.lock` with the four known collisions in a dated exception map.
- `requirements-security.lock:1195` — `mcp==1.29.0` (via semgrep).
- `docs/security.md` / `SECURITY.md` — record the exception and the durable-fix
  pointer; `docs/ci.md` describes the `security-dev` step.

## Commands you will need

| Purpose             | Command                                                             | Provenance | Expected on success            |
|---------------------|---------------------------------------------------------------------|------------|--------------------------------|
| Install/baseline    | `make bootstrap`                                                    | declared   | exit 0                         |
| New env bootstrap   | `make bootstrap-security`                                           | declared   | exit 0 (creates `.venv-security`) |
| Lint / types        | `make lint && make type`                                            | declared   | exit 0                         |
| Unit suite          | `make test`                                                         | declared   | all pass                       |
| Runtime security    | `make security`                                                     | declared   | exit 0 (uses the security env)  |
| Dev security        | `make security-dev`                                                 | declared   | **exit 0 with an empty allowlist** |
| Lock parity         | `make lock-parity-check`                                            | declared   | exit 0, no exceptions           |
| Ledger              | `make plans-ledger-check`                                           | declared   | `validate_plans_ledger: OK`    |

Provenance: all `declared`.

## Scope

**In scope**:

- `Makefile` — `VENV_SECURITY`, `bootstrap-security`, and pointing
  `PIP_AUDIT`/`BANDIT`/`SEMGREP` at it; `.gitignore` entry for the new venv
- `.github/actions/setup-python-env/action.yml` and/or
  `.github/workflows/quality.yml` — provision the second environment (cache key
  must include `requirements-security.lock`)
- `scripts/security_gate.py` — **delete** the `mcp` allowlist entry (and the
  comment block that explains it)
- `scripts/check_lock_parity.py` — empty the four-entry exception map (the
  collisions must no longer exist); keep the script
- `SECURITY.md`, `docs/security.md`, `docs/ci.md` — the new environment and the
  retired exception
- `requirements-security.lock` — only if the split requires a regeneration (it
  should not: the same lock is installed into a different venv)

**Out of scope** (do NOT touch):

- `requirements.lock` / `requirements-refinery.lock` contents.
- The severity mapping and finder logic in `scripts/security_gate.py` (only the
  allowlist entry goes).
- Dropping semgrep from `pyproject.toml`'s `security` extra: keep the extra
  (it documents the tools) — the split is about *where* they are installed.
  If you conclude the extra must change, STOP and report why.

## Git workflow

- Branch: `advisor/156-semgrep-decoupling`
- Conventional commits, e.g.
  `build(security): install the security toolchain in its own environment (plan 156)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

`make bootstrap`, `make lint`, `make type`, `make test`, `make security`,
`make security-dev` (expect green **with** the current allowlist entry), and
`make lock-parity-check`. Record the exact tool versions in `.venv` that the
collisions produce (click/pyee/smmap/types-requests).

**Verify**: all green; the four overridden versions recorded.

### Step 1: Create the security environment

1. Add `VENV_SECURITY ?= .venv-security` next to `VENV_REFINERY`, a stamp, and a
   `bootstrap-security` target that creates the venv and installs
   `requirements-security.lock` with `--require-hashes` (mirror the
   `bootstrap-refinery` recipe exactly).
2. Point `PIP_AUDIT`, `BANDIT`, `SEMGREP` at `$(VENV_SECURITY)`'s interpreter
   module invocation. Check every target that uses them (`security`,
   `security-dev`, `quality`, `quality-ci`, `audit`) and keep the commands
   unchanged otherwise.
3. `.gitignore`: add `.venv-security/`.
4. `make bootstrap` must **stop** installing `requirements-security.lock` into
   `.venv` (that is the whole point); keep installing the runtime lock and the
   pinned dev tools.

**Verify**: `make bootstrap && make bootstrap-security` → both exit 0;
`.venv/bin/python -c "import importlib.metadata as m; print(m.version('click'), m.version('pyee'), m.version('smmap'), m.version('types-requests'))"`
now matches `requirements.lock` exactly; `.venv/lib/python3.13/site-packages`
contains no semgrep/mcp.

### Step 2: Retire the exception

5. Delete the `GHSA-84m7-p3x7-pcfv` entry from `PIP_AUDIT_ALLOWLIST` (and its
   explanatory comment), leaving the structure and the expiry machinery intact.
6. Empty the four-entry exception map in `scripts/check_lock_parity.py` (keep the
   mechanism and its documentation; a future collision must fail the check).
7. `make security-dev` → must exit 0 **without** the allowlist. `make security`
   (runtime lock + bandit + gitleaks) → exit 0. `make lock-parity-check` → exit 0.

**Verify**: the three commands above green; `grep -c "GHSA-84m7" scripts/security_gate.py` → 0.

### Step 3: Provision it in CI

8. Update `.github/actions/setup-python-env/action.yml` (or the quality job
   directly) so CI has both environments, with the cache key including
   `requirements-security.lock`. Keep the runtime venv the one the tests use.
9. Confirm `make security` / `make security-dev` still run in `quality.yml`
   (plan 143 wired `security-dev` there).

**Verify**: the YAML parses; a dry read shows the security step using
`.venv-security`. If you cannot verify CI behaviour locally, say exactly what was
statically verified.

### Step 4: Document the contract

10. `docs/ci.md` (local parity + workflow), `SECURITY.md` / `docs/security.md`:
    the two-environment layout, why (semgrep's incompatible graph and the `mcp`
    pin), and that the exception is retired.
11. **Do not** leave a claim that the advisory is "accepted": it is gone from the
    audited environment; note that semgrep still ships `mcp==1.29.0` in its own
    tool environment, out of the audited scope.

**Verify**: `make docs-check` exits 0; no doc still points at plan 144 as the owner.

## Test plan

- No new unit tests: this is a build/CI change. The verification is the command
  matrix (both venvs, empty allowlist, parity with no exceptions).
- If `scripts/security_gate.py` has tests asserting the allowlist contents (plan
  143 updated one), update them to expect an empty allowlist again.

**Verify**: `make test` green; `make security && make security-dev` green.

## Done criteria

All must hold:

- [ ] `make bootstrap` no longer installs the security lock into `.venv`
- [ ] `make bootstrap-security` creates `.venv-security` from the hash-pinned lock
- [ ] `.venv` matches `requirements.lock` exactly: `make lock-parity-check` exits 0 with an **empty** exception map
- [ ] `PIP_AUDIT_ALLOWLIST` is empty again; `make security-dev` exits 0 without it
- [ ] `make security`, `make quality`, `make quality-ci` exit 0
- [ ] CI provisions both environments; the cache key includes the security lock
- [ ] `make docs-check` exits 0; `.gitignore` covers `.venv-security/`
- [ ] `git diff --name-only main...HEAD` lists only in-scope files
- [ ] `plans/README.md` row 156 updated by the reviewer; `make plans-ledger-check` → OK

## STOP conditions

- Installing `requirements-security.lock` into its own venv fails to resolve (it
  should not: it is a complete lock) → report the resolver output; do not edit
  the lock by hand.
- Removing the security lock from `.venv` breaks a gate that silently depended on
  a tool being there (e.g. `semgrep` used by `quality-ci` without the new venv
  path) → report the target; do not re-add the lock to `.venv`.
- The parity check cannot pass with an empty map because a **new** collision
  appears → report it as a finding (that is the check doing its job).
- CI provisioning would require a third-party action or a paid runner → report.

## Maintenance notes

- Two environments now exist for a reason. `.venv` = runtime + dev tools + the
  app's tests; `.venv-security` = the audited security toolchain; `.venv-refinery`
  = the legacy Streamlit UI. Any future tool with an incompatible graph gets its
  own env, not an override.
- Reviewer should scrutinise: `make security` still audits the **runtime** lock
  (its purpose) while `security-dev` audits the other two locks from the new env;
  no gate accidentally used the wrong interpreter.
- **Deferred:** dropping semgrep entirely (or moving it to a pinned standalone
  binary). Unblocked by a decision that the extra is no longer wanted.
